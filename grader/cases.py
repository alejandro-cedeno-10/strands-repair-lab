"""Hidden acceptance cases generated after the conversation ends."""
import random

def case(name, method, statuses, limit=3):
    return {"name":name,"input":{"method":method,"max_attempts":limit,
            "outcomes":[{"error":"timeout"} if x == "timeout" else {"status":x,"body":{"sequence":i}} for i,x in enumerate(statuses)]}}

def hidden_cases(seed, count=16):
    rng = random.Random(seed)
    cases = [case("matrix-"+m+str(s),m,[s,200],rng.randint(2,5))
             for m in ("GET","HEAD","OPTIONS","PUT","DELETE","POST","PATCH")
             for s in (200,301,400,401,403,404,408,429,500,501,502,503,504)]
    cases += [case("invalid-"+str(i),"GET",[200],v) for i,v in enumerate((0,-1,6,True,1.5,"3",None))]
    cases += [case("exhaustion-"+str(n),"GET",[503],n) for n in range(1,6)]
    cases += [case("exception-"+m,m,[503,"timeout",200]) for m in ("GET","POST")]
    cases += [case("unlisted-method-"+m,m,[503,200]) for m in ("CONNECT","TRACE","PROPFIND")]
    cases += [case("unlisted-status-"+str(s),"GET",[s,200]) for s in (418,505,599)]
    cases += [case("generated-"+str(n),rng.choice(("GET","PUT","POST")),
                   [rng.choice((429,503,401,200)) for _ in range(5)],rng.randint(1,5)) for n in range(count)]
    return cases
