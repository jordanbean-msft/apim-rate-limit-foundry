from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class StreamBackend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: HttpUrl
    path: str = Field(pattern=r"^/[A-Za-z0-9/_.-]+$")
    model: str
    audience: HttpUrl
    api_version: str = ""
    anthropic_version: str = ""

    @model_validator(mode="after")
    def fixed_https_origin(self) -> "StreamBackend":
        for url in (self.endpoint, self.audience):
            if url.scheme != "https" or url.username or url.password or url.query or url.fragment:
                raise ValueError("Stream backends require fixed HTTPS origins")
        if self.endpoint.path not in (None, "/") or self.audience.path not in (None, "/"):
            raise ValueError("Stream endpoint and audience must not contain paths")
        return self
