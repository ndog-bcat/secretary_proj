from dataclasses import dataclass
from datetime import datetime
from pydantic import BaseModel

class TextQueryRequest(BaseModel):
    user_id: str
    request_time: datetime
    user_text: str

class AudioQueryMetadata(BaseModel):
    user_id: str
    request_time: datetime

class QueryResponse(BaseModel):
    message: str
