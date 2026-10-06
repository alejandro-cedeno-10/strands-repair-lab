"""Real local HTTP with the trusted original and reference, never model-written code."""
import threading
import unittest
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from test_controls import reference, known_original

class HTTPIntegration(unittest.TestCase):
    def execute(self, function, method, statuses):
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def respond(self):
                seen.append(self.command)
                self.send_response(statuses[min(len(seen)-1,len(statuses)-1)])
                self.end_headers()
                self.wfile.write(b'controlled response')
            do_GET=respond
            do_POST=respond
            def log_message(self,*args): pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        def send(verb):
            req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port),method=verb)
            try:
                with urllib.request.urlopen(req,timeout=2) as response:
                    return {'status':response.status,'body':response.read().decode()}
            except urllib.error.HTTPError as response:
                try: return {'status':response.code,'body':response.read().decode()}
                finally: response.close()
        try: return function(method,send,3,lambda seconds:None),seen
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_post_duplicate_reproduced(self):
        result,seen=self.execute(known_original.request_with_retry,'POST',[503,200])
        self.assertEqual(len(seen),2)
        self.assertEqual(result['status'],200)

    def test_post_reference_only_once(self):
        result,seen=self.execute(reference,'POST',[503,200])
        self.assertEqual(seen,['POST'])
        self.assertEqual(result['status'],503)

    def test_get_transient_reference_recovers(self):
        result,seen=self.execute(reference,'GET',[503,200])
        self.assertEqual(seen,['GET','GET'])
        self.assertEqual(result['status'],200)

    def test_get_unauthorized_reference_stops(self):
        result,seen=self.execute(reference,'GET',[401,200])
        self.assertEqual(seen,['GET'])
        self.assertEqual(result['status'],401)
