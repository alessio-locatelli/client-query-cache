use std::collections::HashSet;

use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pyo3::types::{
    PyBool, PyByteArray, PyBytes, PyDict, PyFloat, PyInt, PyList, PyRange, PyString, PyTuple,
    PyType,
};
use pyo3::{ffi, intern};

struct Recursion;

impl Recursion {
    fn enter(py: Python<'_>) -> PyResult<Self> {
        if unsafe { ffi::Py_EnterRecursiveCall(c" while preparing a cache key".as_ptr()) } != 0 {
            return Err(PyErr::fetch(py));
        }
        Ok(Self)
    }
}

impl Drop for Recursion {
    fn drop(&mut self) {
        unsafe { ffi::Py_LeaveRecursiveCall() };
    }
}

fn is_string_like(value: &Bound<'_, PyAny>) -> bool {
    value.is_instance_of::<PyString>()
        || value.is_instance_of::<PyBytes>()
        || value.is_instance_of::<PyByteArray>()
}

fn tagged<'py>(tag: &Bound<'py, PyAny>, payload: Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    Ok(PyTuple::new(tag.py(), [tag.clone(), payload])?.into_any())
}

fn items<'py>(
    tag: &Bound<'py, PyAny>,
    values: Vec<Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyAny>> {
    tagged(tag, PyTuple::new(tag.py(), values)?.into_any())
}

fn simple_repr(value: &str) -> Option<String> {
    value
        .bytes()
        .all(|byte| (0x20..=0x7e).contains(&byte) && byte != b'\'' && byte != b'\\')
        .then(|| format!("'{value}'"))
}

fn code_points(value: &Bound<'_, PyString>) -> PyResult<Vec<u8>> {
    Ok(value
        .call_method1(intern!(value.py(), "encode"), ("utf-8", "surrogatepass"))?
        .cast_into::<PyBytes>()?
        .as_bytes()
        .to_vec())
}

#[pyclass(frozen)]
pub(crate) struct Canonicalizer {
    canonical_tag: Py<PyType>,
    pending_tag: Py<PyType>,
    mapping: Py<PyAny>,
    sequence: Py<PyAny>,
    boolean: Py<PyAny>,
    mapping_abc: Py<PyAny>,
    sequence_abc: Py<PyAny>,
    unsupported: Py<PyType>,
    generic: Py<PyAny>,
}

impl Canonicalizer {
    fn is_tag(&self, value: &Bound<'_, PyAny>) -> bool {
        let kind = value.get_type();
        kind.is(&self.canonical_tag) || kind.is(&self.pending_tag)
    }

    fn unsupported(&self, value: &Bound<'_, PyAny>, template: &str) -> PyResult<PyErr> {
        let py = value.py();
        let name = value.get_type().getattr(intern!(py, "__name__"))?.repr()?;
        Ok(PyErr::from_type(
            self.unsupported.bind(py).clone(),
            (template.replacen("{}", &name.to_cow()?, 1),),
        ))
    }

    fn sequence<'py>(&self, values: &Bound<'py, PyAny>) -> PyResult<Vec<Bound<'py, PyAny>>> {
        let _recursion = Recursion::enter(values.py())?;
        if let Ok(tuple) = values.cast_exact::<PyTuple>() {
            return tuple.iter().map(|item| self.value(&item)).collect();
        }
        if let Ok(list) = values.cast_exact::<PyList>() {
            let mut canonical = Vec::with_capacity(list.len());
            let mut index = 0;
            while index < list.len() {
                canonical.push(self.value(&list.get_item(index)?)?);
                index += 1;
            }
            return Ok(canonical);
        }
        values.try_iter()?.map(|item| self.value(&item?)).collect()
    }

    fn mapping<'py>(&self, value: &Bound<'py, PyDict>) -> PyResult<Bound<'py, PyAny>> {
        let py = value.py();
        let _recursion = Recursion::enter(py)?;
        let mut pairs = Vec::with_capacity(value.len());
        for pair in value.call_method0(intern!(py, "items"))?.try_iter()? {
            let pair = pair?;
            let key = self.value(&pair.get_item(0)?)?;
            let item = self.value(&pair.get_item(1)?)?;
            pairs.push(PyTuple::new(py, [key, item])?);
        }
        let mut representations = Vec::with_capacity(pairs.len());
        let mut python_order = false;
        for pair in &pairs {
            let key = pair.get_item(0)?;
            let simple = key
                .cast_exact::<PyString>()
                .ok()
                .and_then(|text| simple_repr(&text.to_cow().ok()?));
            representations.push(match simple {
                Some(text) => Err(text),
                None => {
                    let representation = key.repr()?;
                    python_order |= !representation.is_exact_instance_of::<PyString>();
                    Ok(representation)
                }
            });
        }
        let order: Vec<usize> = if python_order {
            let keys = representations
                .into_iter()
                .map(|representation| match representation {
                    Ok(representation) => Ok(representation.into_any()),
                    Err(text) => Ok(PyString::new(py, &text).into_any()),
                })
                .collect::<PyResult<Vec<_>>>()?;
            let lookup = PyList::new(py, keys)?.getattr(intern!(py, "__getitem__"))?;
            let kwargs = PyDict::new(py);
            kwargs.set_item(intern!(py, "key"), lookup)?;
            py.import(intern!(py, "builtins"))?
                .getattr(intern!(py, "sorted"))?
                .call(
                    (PyRange::new(py, 0, pairs.len().try_into()?)?,),
                    Some(&kwargs),
                )?
                .extract()?
        } else {
            let keys = representations
                .into_iter()
                .map(|representation| match representation {
                    Ok(representation) => code_points(&representation),
                    Err(text) => Ok(text.into_bytes()),
                })
                .collect::<PyResult<Vec<_>>>()?;
            let mut order: Vec<usize> = (0..pairs.len()).collect();
            order.sort_by(|left, right| keys[*left].cmp(&keys[*right]));
            order
        };
        items(
            self.mapping.bind(py),
            order
                .into_iter()
                .map(|index| pairs[index].clone().into_any())
                .collect(),
        )
    }

    fn pending<'py>(
        &self,
        tag: &Bound<'py, PyAny>,
        payload: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let py = tag.py();
        let canonical = tag.getattr(intern!(py, "canonical"))?;
        if tag.getattr(intern!(py, "items"))?.is_truthy()? {
            items(&canonical, self.sequence(payload)?)
        } else {
            let _recursion = Recursion::enter(py)?;
            tagged(&canonical, self.value(payload)?)
        }
    }

    pub(crate) fn value<'py>(&self, value: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        let py = value.py();
        if value.is_exact_instance_of::<PyInt>()
            || value.is_exact_instance_of::<PyString>()
            || value.is_exact_instance_of::<PyBytes>()
            || value.is_none()
        {
            return Ok(value.clone());
        }
        if let Ok(tuple) = value.cast_exact::<PyTuple>() {
            if tuple.len() == 2 {
                let tag = tuple.get_item(0)?;
                let kind = tag.get_type();
                if kind.is(&self.canonical_tag) {
                    return Ok(value.clone());
                }
                if kind.is(&self.pending_tag) {
                    return self.pending(&tag, &tuple.get_item(1)?);
                }
            }
            return items(self.sequence.bind(py), self.sequence(value)?);
        }
        if value.is_exact_instance_of::<PyList>() {
            return items(self.sequence.bind(py), self.sequence(value)?);
        }
        if let Ok(mapping) = value.cast_exact::<PyDict>() {
            return self.mapping(mapping);
        }
        if value.is_exact_instance_of::<PyBool>() {
            return tagged(self.boolean.bind(py), value.clone());
        }
        if value.is_exact_instance_of::<PyFloat>() {
            if value.extract::<f64>()?.is_nan() {
                return Err(self.unsupported(
                    value,
                    "cannot canonicalize a non-reflexive value of type {} for a cache key",
                )?);
            }
            return Ok(value.clone());
        }
        if value.is_instance_of::<PyTuple>()
            || value.is_instance(self.mapping_abc.bind(py))?
            || (value.is_instance(self.sequence_abc.bind(py))? && !is_string_like(value))
        {
            return self.generic.bind(py).call1((value,));
        }
        if let Err(error) = value.hash() {
            if error.is_instance_of::<PyTypeError>(py) {
                return Err(self.unsupported(
                    value,
                    "cannot canonicalize value of type {} for a cache key",
                )?);
            }
            return Err(error);
        }
        if value.ne(value)? {
            return Err(self.unsupported(
                value,
                "cannot canonicalize a non-reflexive value of type {} for a cache key",
            )?);
        }
        Ok(value.clone())
    }
}

#[pymethods]
impl Canonicalizer {
    #[new]
    #[allow(
        clippy::too_many_arguments,
        reason = "Python supplies each canonical tag and fallback once at import"
    )]
    fn new(
        canonical_tag: Py<PyType>,
        pending_tag: Py<PyType>,
        mapping: Py<PyAny>,
        sequence: Py<PyAny>,
        boolean: Py<PyAny>,
        mapping_abc: Py<PyAny>,
        sequence_abc: Py<PyAny>,
        unsupported: Py<PyType>,
        generic: Py<PyAny>,
    ) -> Self {
        Self {
            canonical_tag,
            pending_tag,
            mapping,
            sequence,
            boolean,
            mapping_abc,
            sequence_abc,
            unsupported,
            generic,
        }
    }

    fn canonical<'py>(&self, value: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        self.value(value)
    }
}

const MAPPING: usize = 0;
const SEQUENCE: usize = 1;
const FLOAT: usize = 2;
const INT64: usize = 3;

pub(crate) enum Pending<'py> {
    Leaf(Bound<'py, PyAny>),
    Items(usize, Vec<Pending<'py>>),
    Wrapped(usize, Bound<'py, PyAny>),
}

#[pyclass(frozen)]
pub(crate) struct OrderedKeys {
    canonicalizer: Py<Canonicalizer>,
    pending_tags: [Py<PyAny>; 4],
    canonical_tags: [Py<PyAny>; 4],
    int64_type: Py<PyAny>,
    decimal_type: Py<PyAny>,
    generic: Py<PyAny>,
    generic_discriminator: Py<PyAny>,
}

impl OrderedKeys {
    fn sequence<'py>(
        &self,
        values: &Bound<'py, PyAny>,
        distinguish: bool,
    ) -> PyResult<Vec<Pending<'py>>> {
        let _recursion = Recursion::enter(values.py())?;
        if let Ok(tuple) = values.cast_exact::<PyTuple>() {
            return tuple
                .iter()
                .map(|item| self.structure(&item, distinguish))
                .collect();
        }
        let list = values.cast_exact::<PyList>()?;
        let mut pending = Vec::with_capacity(list.len());
        let mut index = 0;
        while index < list.len() {
            pending.push(self.structure(&list.get_item(index)?, distinguish)?);
            index += 1;
        }
        Ok(pending)
    }

    pub(crate) fn structure<'py>(
        &self,
        value: &Bound<'py, PyAny>,
        distinguish: bool,
    ) -> PyResult<Pending<'py>> {
        let py = value.py();
        if value.is_exact_instance_of::<PyInt>()
            || value.is_exact_instance_of::<PyString>()
            || value.is_exact_instance_of::<PyBytes>()
            || value.is_exact_instance_of::<PyBool>()
            || value.is_none()
        {
            return Ok(Pending::Leaf(value.clone()));
        }
        if let Ok(tuple) = value.cast_exact::<PyTuple>() {
            if tuple.len() == 2 && self.canonicalizer.get().is_tag(&tuple.get_item(0)?) {
                return Ok(Pending::Leaf(value.clone()));
            }
            return Ok(Pending::Items(SEQUENCE, self.sequence(value, distinguish)?));
        }
        if value.is_exact_instance_of::<PyList>() {
            return Ok(Pending::Items(SEQUENCE, self.sequence(value, distinguish)?));
        }
        if let Ok(mapping) = value.cast_exact::<PyDict>() {
            let _recursion = Recursion::enter(py)?;
            let mut pending = Vec::with_capacity(mapping.len() * 2);
            for pair in mapping.call_method0(intern!(py, "items"))?.try_iter()? {
                let pair = pair?;
                pending.push(self.structure(&pair.get_item(0)?, distinguish)?);
                pending.push(self.structure(&pair.get_item(1)?, distinguish)?);
            }
            return Ok(Pending::Items(MAPPING, pending));
        }
        if value.is_exact_instance_of::<PyFloat>() {
            return Ok(if distinguish {
                Pending::Wrapped(FLOAT, value.clone())
            } else {
                Pending::Leaf(value.clone())
            });
        }
        let canonicalizer = self.canonicalizer.get();
        if value.is_instance_of::<PyTuple>()
            || value.is_instance(canonicalizer.mapping_abc.bind(py))?
            || (value.is_instance(canonicalizer.sequence_abc.bind(py))? && !is_string_like(value))
        {
            let generic = if distinguish {
                &self.generic_discriminator
            } else {
                &self.generic
            };
            return Ok(Pending::Leaf(generic.bind(py).call1((value,))?));
        }
        if distinguish {
            if value.is_instance(self.int64_type.bind(py))? {
                return Ok(Pending::Wrapped(INT64, value.clone()));
            }
            if value.is_instance_of::<PyFloat>() {
                return Ok(Pending::Wrapped(FLOAT, value.clone()));
            }
        } else if value.is_instance(self.decimal_type.bind(py))? {
            return Ok(Pending::Leaf(
                value.call_method0(intern!(py, "to_decimal"))?,
            ));
        }
        Ok(Pending::Leaf(value.clone()))
    }

    pub(crate) fn finish<'py>(
        &self,
        py: Python<'py>,
        pending: Pending<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let canonicalizer = self.canonicalizer.get();
        match pending {
            Pending::Leaf(value) => canonicalizer.value(&value),
            Pending::Wrapped(tag, value) => {
                let _recursion = Recursion::enter(py)?;
                tagged(
                    self.canonical_tags[tag].bind(py),
                    canonicalizer.value(&value)?,
                )
            }
            Pending::Items(tag, children) => {
                let _recursion = Recursion::enter(py)?;
                let values = children
                    .into_iter()
                    .map(|child| self.finish(py, child))
                    .collect::<PyResult<Vec<_>>>()?;
                items(self.canonical_tags[tag].bind(py), values)
            }
        }
    }

    fn materialize<'py>(
        &self,
        py: Python<'py>,
        pending: Pending<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        match pending {
            Pending::Leaf(value) => Ok(value),
            Pending::Wrapped(tag, value) => tagged(self.pending_tags[tag].bind(py), value),
            Pending::Items(tag, children) => {
                let values = children
                    .into_iter()
                    .map(|child| self.materialize(py, child))
                    .collect::<PyResult<Vec<_>>>()?;
                items(self.pending_tags[tag].bind(py), values)
            }
        }
    }

    pub(crate) fn canonical<'py>(
        &self,
        value: &Bound<'py, PyAny>,
        distinguish: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        self.finish(value.py(), self.structure(value, distinguish)?)
    }

    pub(crate) fn canonicalizer(&self) -> &Canonicalizer {
        self.canonicalizer.get()
    }
}

#[pymethods]
impl OrderedKeys {
    #[new]
    fn new(
        py: Python<'_>,
        canonicalizer: Py<Canonicalizer>,
        pending_tags: [Py<PyAny>; 4],
        int64_type: Py<PyAny>,
        decimal_type: Py<PyAny>,
        generic: Py<PyAny>,
        generic_discriminator: Py<PyAny>,
    ) -> PyResult<Self> {
        let canonical = |tag: &Py<PyAny>| -> PyResult<Py<PyAny>> {
            Ok(tag.bind(py).getattr(intern!(py, "canonical"))?.unbind())
        };
        let canonical_tags = [
            canonical(&pending_tags[MAPPING])?,
            canonical(&pending_tags[SEQUENCE])?,
            canonical(&pending_tags[FLOAT])?,
            canonical(&pending_tags[INT64])?,
        ];
        Ok(Self {
            canonicalizer,
            pending_tags,
            canonical_tags,
            int64_type,
            decimal_type,
            generic,
            generic_discriminator,
        })
    }

    fn key<'py>(&self, value: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        self.canonical(value, false)
    }

    fn discriminator<'py>(&self, value: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        self.canonical(value, true)
    }

    fn pending_key<'py>(&self, value: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        self.materialize(value.py(), self.structure(value, false)?)
    }

    fn pending_discriminator<'py>(&self, value: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        self.materialize(value.py(), self.structure(value, true)?)
    }
}

#[pyclass(frozen)]
pub(crate) struct UnsafeScan {
    keys: HashSet<String>,
    key_set: Py<PyAny>,
    variables: HashSet<String>,
    prefixes: Vec<String>,
    mapping_abc: Py<PyAny>,
    sequence_abc: Py<PyAny>,
    generic: Py<PyAny>,
}

impl UnsafeScan {
    fn delegate(&self, node: &Bound<'_, PyAny>) -> PyResult<bool> {
        let py = node.py();
        self.generic
            .bind(py)
            .call1((node, self.key_set.bind(py)))?
            .is_truthy()
    }

    fn scan(&self, node: &Bound<'_, PyAny>) -> PyResult<bool> {
        let py = node.py();
        if node.is_exact_instance_of::<PyInt>()
            || node.is_exact_instance_of::<PyFloat>()
            || node.is_exact_instance_of::<PyBool>()
            || node.is_exact_instance_of::<PyBytes>()
            || node.is_exact_instance_of::<PyByteArray>()
            || node.is_none()
        {
            return Ok(false);
        }
        if let Ok(mapping) = node.cast_exact::<PyDict>() {
            let _recursion = Recursion::enter(py)?;
            for pair in mapping.call_method0(intern!(py, "items"))?.try_iter()? {
                let pair = pair?;
                let key = pair.get_item(0)?;
                let unsafe_key = if let Ok(text) = key.cast_exact::<PyString>() {
                    self.keys.contains(text.to_string_lossy().as_ref())
                } else {
                    !key.is_instance_of::<PyString>() || self.key_set.bind(py).contains(&key)?
                };
                if unsafe_key || self.scan(&pair.get_item(1)?)? {
                    return Ok(true);
                }
            }
            return Ok(false);
        }
        if let Ok(text) = node.cast_exact::<PyString>() {
            let text = text.to_string_lossy();
            return Ok(self.variables.contains(text.as_ref())
                || self
                    .prefixes
                    .iter()
                    .any(|prefix| text.starts_with(prefix.as_str())));
        }
        if let Ok(tuple) = node.cast_exact::<PyTuple>() {
            let _recursion = Recursion::enter(py)?;
            for item in tuple.iter() {
                if self.scan(&item)? {
                    return Ok(true);
                }
            }
            return Ok(false);
        }
        if let Ok(list) = node.cast_exact::<PyList>() {
            let _recursion = Recursion::enter(py)?;
            let mut index = 0;
            while index < list.len() {
                if self.scan(&list.get_item(index)?)? {
                    return Ok(true);
                }
                index += 1;
            }
            return Ok(false);
        }
        if node.is_instance_of::<PyDict>()
            || node.is_instance(self.mapping_abc.bind(py))?
            || node.is_instance_of::<PyString>()
            || (node.is_instance(self.sequence_abc.bind(py))?
                && !node.is_instance_of::<PyBytes>()
                && !node.is_instance_of::<PyByteArray>())
        {
            return self.delegate(node);
        }
        Ok(false)
    }
}

#[pymethods]
impl UnsafeScan {
    #[new]
    fn new(
        key_set: &Bound<'_, PyAny>,
        variables: &Bound<'_, PyAny>,
        prefixes: &Bound<'_, PyAny>,
        mapping_abc: Py<PyAny>,
        sequence_abc: Py<PyAny>,
        generic: Py<PyAny>,
    ) -> PyResult<Self> {
        Ok(Self {
            keys: key_set.extract()?,
            key_set: key_set.clone().unbind(),
            variables: variables.extract()?,
            prefixes: prefixes.extract()?,
            mapping_abc,
            sequence_abc,
            generic,
        })
    }

    fn __call__(&self, node: &Bound<'_, PyAny>) -> PyResult<bool> {
        self.scan(node)
    }
}
