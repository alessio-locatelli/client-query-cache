from datetime import datetime

import polars as pl

df = pl.DataFrame(
    {
        "_id": [1, 2, 3],
        "date": [datetime(2025, 1, 1), datetime(2025, 1, 2), datetime(2025, 1, 3)],
        "float": [4.0, 5.0, 6.0],
        "string": ["a", "b", "c"],
        "mixed": [[False], ["foobar"], [1.0]],
    },
    schema=[
        "_id",
        "date",
        "float",
        "string",
        ("mixed", pl.List),
    ],
)

print(df)


df2 = pl.DataFrame({
    "_id": [4],
    "a": [2],
    "d": [4],
})

df_concat = pl.concat([df, df2], how="diagonal")
print(df_concat)
print(type(df_concat["mixed"][0]["column_0"]))
