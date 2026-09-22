# idea_board.v0_1 samples (2026-09-21 PT)

Normalized Trade Machine and Options AI boards from the desk sync. Shadow/paper
only. `shareKey` values in the Trade Machine sample are `[REDACTED]`.

The Options AI file is a DOM QuickStrike board, not a HAR normalize.
`get_ideas.py` will not build Options AI ideas from chain or quote JSON.
The capture HAR is not in git. `redact_har.py` fails closed on unsupported
encodings and refuses a raw output filename.

Do not treat prices in the Options AI sample as live fills or as an order ticket.
