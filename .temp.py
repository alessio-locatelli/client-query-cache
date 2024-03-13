def f():
    {}.get("foo")


def g():
    try:
        {}["foo"]
    except KeyError:
        pass


import timeit

print(timeit.timeit("f()", globals=globals()))
print(timeit.timeit("g()", globals=globals()))
