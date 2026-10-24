# Plugin interface
One file per capability: plugins/<name>.py (files starting with _ are ignored).

    NAME = "my_tool"
    DESCRIPTION = "my_tool(arg) - what it does, how to call it"
    def run(**kwargs): ...        # returns a string
    def selftest(): ...           # raise on failure; keep it fast

The agent sees NAME + DESCRIPTION as a tool. New tech = new plugin file.
