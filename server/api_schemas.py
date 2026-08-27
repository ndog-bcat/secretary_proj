from datetime import datetime
from pydantic import BaseModel

class TextQueryRequest(BaseModel):
    user_id: str
    request_time: datetime
    user_text: str

class TextQueryResponse(BaseModel):
    message: str