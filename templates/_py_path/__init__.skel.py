
class error(Exception):
    '''generic error class for throwing exceptions'''

    def __init__(self, fmt, *args):
        self.message = fmt % args

    def __str__(self):
        return self.message

class Paths:
    def __init__(self, root):
        self.root = root
        self.ns   = ns

    def __call__(self, *args):
        {% if namespace %}
        return os.path.join(self.root, {{ namespace }}, *args)
        {% else %}
        return os.path.join(self.root, *args)
        {% end %}

    # support / as a path joiner
    def __truediv__(self, other):
        return Paths(self(other))

    def __str__(self):
        return self()
