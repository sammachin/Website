from main import db
from . import BaseModel


# entered-lottery -- An entry in the lottery for a ticket
# ticket -- either a converted lottery ticket or a simply issued ticket
# lost-lottery -- did not convert from a lottery ticket to an actual ticket
# cancelled -- with drawn/returned. Either as an actual ticket or a lottery ticket

EVENT_TICKET_STATES = {
    "entered-lottery": ["ticket", "lost-lottery", "cancelled"],
    "ticket": ["cancelled"],
    "lost-lottery": ["cancelled"],
    "cancelled": [],
}


class EventTicket(BaseModel):
    __tablename__ = "event_ticket"

    id = db.Column(db.Integer, primary_key=True)
    state = db.Column(db.String, nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("proposal.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    rank = db.Column(db.Integer, nullable=False)
