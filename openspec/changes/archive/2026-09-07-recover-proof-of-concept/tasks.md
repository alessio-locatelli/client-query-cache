## 1. Classify the prototype boundary

- [x] 1.1 Inventory experimental exports, subclass behavior, and tests; publish a retained/replaced/removed compatibility map verified against the current package.
- [x] 1.2 Add regression tests that protect caller-owned client lifecycle and raw-PyMongo fallback before removing prototype paths.

## 2. Establish composed construction

- [x] 2.1 Introduce composed manager and collection-facade construction around supplied PyMongo clients; verify no supported entry point subclasses or replaces a caller client.
- [x] 2.2 Remove or deprecate prototype entry points according to the compatibility map; verify affected imports fail or migrate exactly as documented.

## 3. Publish migration evidence

- [x] 3.1 Add incremental migration guidance and a raw-collection escape hatch example; verify its code uses only the supported construction API.
