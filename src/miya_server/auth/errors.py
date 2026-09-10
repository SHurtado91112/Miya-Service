class AuthError(Exception):
    """Any failure in the sign-in / refresh path.

    Deliberately coarse: the client is told "sign-in failed", never *why*.
    Distinguishing "no such user" from "bad signature" from "expired" gives an
    attacker a probing oracle, and none of it is actionable for a legitimate
    caller -- their only recourse is to sign in again. The specific cause is
    logged server-side instead.
    """
