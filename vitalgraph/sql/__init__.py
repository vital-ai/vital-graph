import logging

__version__ = "vital_0_0_1"

class NullHandler(logging.Handler):
    """
    Null handler.

    c.f.
    http://docs.python.org/howto/logging.html#library-config
    and
    http://docs.python.org/release/3.1.3/library/logging.\
    html#configuring-logging-for-a-library
    """

    def emit(self, record):
        """Emit."""
        pass


hndlr = NullHandler()
logging.getLogger("rdflib").addHandler(hndlr)


def registerplugins():
    """
    Register plugins.

    If setuptools is used to install rdflib-sqlalchemy, all the provided
    plugins are registered through entry_points. This is strongly recommended.

    However, if only distutils is available, then the plugins must be
    registered manually.

    This method will register all of the rdflib-sqlalchemy Store plugins.

    """
    from rdflib.store import Store
    from rdflib import plugin

    try:
        plugin.get("VitalGraph", Store)
    except plugin.PluginException:
        pass

    # Register the plugins ...

    plugin.register(
        "VitalGraph",
        Store,
        "vitalgraph.sql",
        "VitalGraphSQLStore",
    )
