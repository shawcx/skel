#
# The MIT License (MIT)
#
# Copyright (c) 2023-2025 Matthew Shaw
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#

import functools
import inspect
import json

__all__ = ['jsxn']


class _Jsxn:
    # Required for the derived class to be also be slotted
    __slots__ = []

    def __init__(self, *args, **kwds):
        # Call the instance with the passed arguments.
        self(*args, **kwds)
        # Support partial initialization by setting undefined fields to null.
        for attr in self.__slots__:
            if not hasattr(self, attr):
                setattr(self, attr, None)

    def __call__(self, *args, **kwds):
        # Calling jsxn instances accepts a variety of types. This block assigns
        # values to the attributes based on the type of arguments passed in.
        if not args:
            args = kwds
        elif len(args) == 1:
            args = args[0]
        else:
            raise ValueError('Only one unnamed argument can be passed')

        # If args is string it must be JSON
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.decoder.JSONDecodeError:
                raise ValueError('String arguments must be valid JSON')

        if isinstance(args, dict):
            for key,value in args.items():
                setattr(self, key, value)
        elif isinstance(args, _Jsxn):
            for key,value in args:
                setattr(self, key, value)
        else:
            raise ValueError('Invalid type') from None

        return self

    def __getitem__(self, name):
        # Support access attributes via indices.
        return getattr(self, name)

    def __setitem__(self, name, value):
        setattr(self, name, value)

    def __iter__(self):
        # This is for passing jsxn instances to the dict constructor.
        for attr in self.__slots__:
            yield((attr, getattr(self, attr)))

    def __len__(self):
        return len(self.__slots__)

    def __str__(self):
        # Use JSON for string representations of the jsxn instance.
        return json.dumps(dict(self))


# The _Cache class is used to hold the generated classes. It is defined outside
# of _JsxnFactory in order to reduce the potential for any name collisions with
# the names used by consumers of the library.
class _Cache(dict):
    def _generate(self, _name, *args, **kwds):
        # Creation of jsxn classes accepts a variety of types when specifying
        # the schema of the class. This block derives the slots based on
        # the arguments passed in.

        # Default to a bare jsxn class
        inherit = (_Jsxn,)

        # Determine what is going to be used for slots
        if not args:
            slots = kwds
        elif len(args) == 1:
            if isinstance(args[0], type):
                if not issubclass(args[0], _Jsxn):
                    inherit = (args[0],_Jsxn)
                else:
                    inherit = (args[0],)
            slots = args[0]
        else:
            raise ValueError('Only one unnamed argument can be passed')

        # If args is string it must be JSON
        if isinstance(slots, str):
            try:
                slots = json.loads(slots)
            except json.decoder.JSONDecodeError:
                raise ValueError('String arguments must be valid JSON')

        # Use dictionary keys
        if isinstance(slots, dict):
            slots = tuple(slots.keys())
        # Else use existing slots
        elif hasattr(slots, '__slots__'):
            slots = slots.__slots__
        # Or derive from annotations
        elif hasattr(slots, '__annotations__'):
            slots = tuple(slots.__annotations__.keys())
        # Finally assume it is a list
        elif not isinstance(slots, list):
            raise ValueError('Invalid type')

        # Cache the derived jsxn class.
        self[_name] = type(_name, tuple(inherit), {'__slots__':slots})

        return self[_name]

    def _instantiate(self, _name, *args, **kwds):
        # Return the instantiated class
        cls = self._generate(_name, *args, **kwds)
        return cls(*args, **kwds)


# Instantiate the cache dictionary.
_cache = _Cache()


# _JsxnFactory manages the creation and access to jsxn classes. When a derived
# class is accessed it will return the cached jsxn class. If the jsxn class has
# not been defined it will return a curried _Cache.generate function with the
# attribute name bound as the first argument
class _JsxnFactory:
    # Let the instance be a decorator function.
    def __call__(self, arg=None):
        # Helpher function to inject a class into an existing jsnx class.
        def inject(name, cls):
            if name in _cache:
                og = _cache[name]
                cls = type(name, (og,cls), {'__slots__':og.__slots__})
            return _cache._generate(name, cls)

        # If a string is passed in use that as the name.
        if isinstance(arg, str):
            def wrap(cls):
                return inject(arg, cls)
            return wrap
        # Use the class name if no argument is supplied
        elif arg is None:
            def wrap(cls):
                return inject(cls.__name__, cls)
            return wrap
        # Use the class name when not called as a function
        elif inspect.isclass(arg):
            return inject(arg.__name__, arg)
        # Raise error in all other circumstances
        raise TypeError(arg)

    def __getattr__(self, name):
        # Access jsxn classes via attribute
        try:
            self.__getattribute__(name)
        except AttributeError:
            return self[name]

    def __getitem__(self, name):
        # Return existing or instantiate a new jsxn class
        try:
            return _cache[name]
        except KeyError:
            return functools.partial(_cache._instantiate, name)

    def __delattr__(self, name):
        # Support deleting jsxn classes
        try:
            del _cache[name]
        except KeyError:
            raise AttributeError(name) from None

    def __delitem__(self, name):
        # Support deleting jsxn classes
        del _cache[name]

# This is the way to access the jsxn library.
jsxn = _JsxnFactory()
