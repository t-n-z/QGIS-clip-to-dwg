def classFactory(iface):
    from .plugin import ClipToDwgPlugin
    return ClipToDwgPlugin(iface)
