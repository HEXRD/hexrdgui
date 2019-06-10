try:
    import importlib.resources as importlib_resources
except ImportError:
    # Try backported to PY<37 `importlib_resources`.
    import importlib_resources

def load_resource(module, name):
    """This will return a string of a resource's contents"""
    return importlib_resources.read_text(module, name)
