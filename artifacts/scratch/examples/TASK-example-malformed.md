# auth stuff

need to fix the auth thing

## todo

1. look at the code
2. change it
3. test it maybe?

things to remember:
- sessions are weird
- api keys exist
- dont break prod

## random notes

talked to someone about this, they said its fine

the verify_session thing is in interfaces somewhere, grep for it

## done?

idk if this works yet. try running the server and logging in.

also check the api key thing with curl:
curl -H "X-API-Key: test" localhost:8000/api/v1/info

if that works we're probably good

---

update: found a bug, will fix later

update 2: fixed it i think

update 3: nope still broken, see slack thread
