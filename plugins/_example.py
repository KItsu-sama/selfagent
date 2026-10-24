NAME = "example"
DESCRIPTION = "example(text) - echoes text back"
def run(text=""): return text
def selftest(): assert run("a") == "a"
