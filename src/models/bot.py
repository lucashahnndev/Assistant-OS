from pydantic import BaseModel
import date_and_hour as dah

class response(BaseModel):
    response: str
    type_response: str
    date: dah.date_and_time()

