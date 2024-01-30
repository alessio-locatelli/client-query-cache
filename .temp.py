class A:
    def __init__(self):
        self.__db = "foobar"


class B(A):
    def func(self):
        print(self._A__db)


b = B()
b.func()
