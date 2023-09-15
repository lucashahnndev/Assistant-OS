from pydantic import BaseModel
import date_and_hour as dah

class user(BaseModel):
    id: str
    name: str
    date: dah.date_and_time()
    user_input: str