class HTML:
    def __init__(self, string: str, base_url: str | None = None):
        self.string = string
        self.base_url = base_url

    def write_pdf(self, stream):
        stream.write(b"PDF")
        stream.flush() if hasattr(stream, "flush") else None
