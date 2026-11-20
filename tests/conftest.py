import os

# The tests check the English messages, whatever the language of the machine.
os.environ["LANGUAGE"] = "en"

# GNOME unless a test picks Plasma itself, whatever desktop runs the tests.
os.environ["XDG_CURRENT_DESKTOP"] = "GNOME"
