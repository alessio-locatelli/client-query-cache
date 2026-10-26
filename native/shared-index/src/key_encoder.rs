//! The shared key envelope follows https://bsonspec.org/spec.html. Specialized
//! scalar representations stay with the Python wire codec and PyMongo's encoder.
use std::collections::HashMap;

use pyo3::exceptions::{PyOverflowError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes, PyDict, PyFloat, PyInt, PyString, PyTuple};

type FindKeys<'py> = (Bound<'py, PyBytes>, Bound<'py, PyBytes>);

struct Recursion;

impl Recursion {
    fn enter(py: Python<'_>) -> PyResult<Self> {
        // CPython's recursion guard covers calls crossing the extension boundary.
        if unsafe { pyo3::ffi::Py_EnterRecursiveCall(c" while encoding a cache key".as_ptr()) } != 0
        {
            return Err(PyErr::fetch(py));
        }
        Ok(Self)
    }
}

impl Drop for Recursion {
    fn drop(&mut self) {
        unsafe { pyo3::ffi::Py_LeaveRecursiveCall() };
    }
}

fn encoded_value(encoded: &[u8]) -> PyResult<(u8, &[u8])> {
    match encoded {
        [a, b, c, d, kind, b'k', 0, payload @ .., 0]
            if usize::try_from(i32::from_le_bytes([*a, *b, *c, *d])).ok()
                == Some(encoded.len()) =>
        {
            Ok((*kind, payload))
        }
        _ => Err(PyValueError::new_err("invalid encoded key envelope")),
    }
}

fn length(value: usize) -> PyResult<[u8; 4]> {
    i32::try_from(value)
        .map(i32::to_le_bytes)
        .map_err(|_| PyOverflowError::new_err("cache key exceeds BSON length"))
}

fn start(buffer: &mut Vec<u8>) -> usize {
    let offset = buffer.len();
    buffer.extend_from_slice(&[0; 4]);
    offset
}

fn finish(buffer: &mut Vec<u8>, offset: usize) -> PyResult<()> {
    buffer.push(0);
    let size = length(buffer.len() - offset)?;
    buffer[offset..offset + 4].copy_from_slice(&size);
    Ok(())
}

fn header(buffer: &mut Vec<u8>, kind: u8, name: &str) {
    buffer.push(kind);
    buffer.extend_from_slice(name.as_bytes());
    buffer.push(0);
}

fn string(buffer: &mut Vec<u8>, name: &str, value: &str) -> PyResult<()> {
    header(buffer, 2, name);
    buffer.extend_from_slice(&length(value.len() + 1)?);
    buffer.extend_from_slice(value.as_bytes());
    buffer.push(0);
    Ok(())
}

fn tagged(buffer: &mut Vec<u8>, name: &str, tag: &str) -> PyResult<usize> {
    header(buffer, 3, name);
    let offset = start(buffer);
    string(buffer, "t", tag)?;
    Ok(offset)
}

fn tuple(buffer: &mut Vec<u8>, name: &str) -> PyResult<(usize, usize)> {
    let document = tagged(buffer, name, "tuple")?;
    header(buffer, 4, "p");
    Ok((document, start(buffer)))
}

fn finish_tuple(buffer: &mut Vec<u8>, offsets: (usize, usize)) -> PyResult<()> {
    finish(buffer, offsets.1)?;
    finish(buffer, offsets.0)
}

#[pyclass(frozen)]
pub(crate) struct FindKeyEncoder {
    tags: HashMap<usize, String>,
    scalar_encoder: Py<PyAny>,
}

impl FindKeyEncoder {
    fn node(&self, buffer: &mut Vec<u8>, name: &str, value: &Bound<'_, PyAny>) -> PyResult<()> {
        if let Ok(items) = value.cast::<PyTuple>() {
            let _recursion = Recursion::enter(value.py())?;
            let offsets = tuple(buffer, name)?;
            for (index, item) in items.iter().enumerate() {
                self.node(buffer, &index.to_string(), &item)?;
            }
            return finish_tuple(buffer, offsets);
        }
        if let Some(tag) = self.tags.get(&(value.as_ptr() as usize)) {
            let offset = tagged(buffer, name, "tag")?;
            string(buffer, "p", tag)?;
            return finish(buffer, offset);
        }
        if value.is_none() {
            header(buffer, 10, name);
        } else if value.is_exact_instance_of::<PyBool>() {
            header(buffer, 8, name);
            buffer.push(u8::from(value.extract::<bool>()?));
        } else if value.is_exact_instance_of::<PyInt>() {
            if let Ok(integer) = value.extract::<i64>() {
                let offset = tagged(buffer, name, "int")?;
                header(buffer, 18, "p");
                buffer.extend_from_slice(&integer.to_le_bytes());
                finish(buffer, offset)?;
            } else {
                self.scalar(buffer, name, value)?;
            }
        } else if value.is_exact_instance_of::<PyString>() {
            string(buffer, name, value.cast::<PyString>()?.to_str()?)?;
        } else if value.is_exact_instance_of::<PyBytes>() {
            let bytes = value.cast::<PyBytes>()?.as_bytes();
            header(buffer, 5, name);
            buffer.extend_from_slice(&length(bytes.len())?);
            buffer.push(0);
            buffer.extend_from_slice(bytes);
        } else if value.is_exact_instance_of::<PyFloat>() {
            header(buffer, 1, name);
            buffer.extend_from_slice(&value.extract::<f64>()?.to_le_bytes());
        } else {
            self.scalar(buffer, name, value)?;
        }
        Ok(())
    }

    fn scalar(&self, buffer: &mut Vec<u8>, name: &str, value: &Bound<'_, PyAny>) -> PyResult<()> {
        let encoded = self.scalar_encoder.call1(value.py(), (value,))?;
        let bytes = encoded.bind(value.py()).cast::<PyBytes>()?.as_bytes();
        // The existing encoder returns one BSON element named "k". Reuse its
        // complete value, including BSON subtype and specialized tagged nodes.
        let (kind, payload) = encoded_value(bytes)?;
        header(buffer, kind, name);
        buffer.extend_from_slice(payload);
        Ok(())
    }
}

#[pymethods]
impl FindKeyEncoder {
    #[new]
    fn new(tags: &Bound<'_, PyDict>, scalar_encoder: Py<PyAny>) -> PyResult<Self> {
        let tags = tags
            .iter()
            .map(|(identity, name)| Ok((identity.extract::<usize>()?, name.extract::<String>()?)))
            .collect::<PyResult<_>>()?;
        Ok(Self {
            tags,
            scalar_encoder,
        })
    }

    fn encode<'py>(
        &self,
        py: Python<'py>,
        family: &Bound<'py, PyAny>,
        limit: &Bound<'py, PyAny>,
    ) -> PyResult<FindKeys<'py>> {
        let mut family_bytes = Vec::with_capacity(256);
        let root = start(&mut family_bytes);
        self.node(&mut family_bytes, "k", family)?;
        finish(&mut family_bytes, root)?;

        let exact = self.wrap(py, &family_bytes, limit)?;
        Ok((PyBytes::new(py, &family_bytes), exact))
    }

    fn wrap<'py>(
        &self,
        py: Python<'py>,
        family_bytes: &[u8],
        limit: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let mut exact = Vec::with_capacity(family_bytes.len() + 128);
        let root = start(&mut exact);
        let outer = tuple(&mut exact, "k")?;
        let tag = tagged(&mut exact, "0", "tag")?;
        string(&mut exact, "p", "canonical-seq")?;
        finish(&mut exact, tag)?;
        let pair = tuple(&mut exact, "1")?;
        let (kind, payload) = encoded_value(family_bytes)?;
        header(&mut exact, kind, "0");
        exact.extend_from_slice(payload);
        self.node(&mut exact, "1", limit)?;
        finish_tuple(&mut exact, pair)?;
        finish_tuple(&mut exact, outer)?;
        finish(&mut exact, root)?;
        Ok(PyBytes::new(py, &exact))
    }
}
