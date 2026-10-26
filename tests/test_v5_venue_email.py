from agents import loop

def test_email_address_is_not_a_venue_ask():
    s = ("Could you please confirm whether I need to provide the email address of my other guest, "
         "and whether they can also join the official Facebook group?")
    assert not loop._VENUE_ASK.search(s)

def test_venue_address_still_matches():
    assert loop._VENUE_ASK.search("What is the address of the event?")
    assert loop._VENUE_ASK.search("Which hotel is the venue?")
