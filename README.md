# mongodb-client-cache

MongoDB client-side cache

---

## Features

- Easy to use: add to your existing project with a single line of code
- 100% test coverage
- Performance matters: the code is benchmarked and stress tested.
- Latest Python and `pymongo`
- Lightweight: pure Python, not bloated with external dependencies.

## Limitations

You cannot remove the `_id` field from the results by setting it to `0` in the projection. We use the `_id` field to manage cached documents.

## Recommendations

```py
# Bad:
collection.find()
```
