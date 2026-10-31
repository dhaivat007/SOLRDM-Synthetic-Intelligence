"""Constrained Wikipedia search and retrieval. Search results are untrusted evidence."""
import json, re, urllib.parse, urllib.request
from dataclasses import dataclass

API='https://en.wikipedia.org/w/api.php'
MAX_BYTES=350_000
@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    source: str = 'Wikipedia'

class InternetResearch:
    def __init__(self, transport=None):
        # Injectable transport allows tests without internet.
        self.transport=transport or self._request

    @staticmethod
    def _request(params):
        url=API+'?'+urllib.parse.urlencode(params)
        req=urllib.request.Request(url,headers={'User-Agent':'SOLRDM-Research/0.4 (educational prototype; no bulk crawling)','Accept':'application/json'})
        with urllib.request.urlopen(req,timeout=8) as response:
            if response.geturl().split('?')[0] != API: raise ValueError('Redirect rejected')
            body=response.read(MAX_BYTES+1)
            if len(body)>MAX_BYTES: raise ValueError('Response too large')
            return json.loads(body.decode('utf-8'))

    def search(self,query,limit=5):
        if not isinstance(query,str) or not 2<=len(query.strip())<=120: raise ValueError('Invalid query')
        if not isinstance(limit,int) or not 1<=limit<=10: raise ValueError('Invalid limit')
        data=self.transport({'action':'query','list':'search','srsearch':query,'srlimit':limit,'format':'json','utf8':'1'})
        hits=[]
        for item in data.get('query',{}).get('search',[])[:limit]:
            title=item.get('title','')
            if not isinstance(title,str) or not title: continue
            hits.append(SearchHit(title,'https://en.wikipedia.org/wiki/'+urllib.parse.quote(title.replace(' ','_')),
                                  re.sub(r'<[^>]*>','',str(item.get('snippet','')))[:500]))
        return hits

    def extract(self,title):
        if not isinstance(title,str) or not 1<=len(title)<=200: raise ValueError('Invalid title')
        data=self.transport({'action':'query','prop':'extracts','explaintext':'1','exintro':'1',
                             'titles':title,'format':'json','redirects':'1'})
        pages=data.get('query',{}).get('pages',{})
        for page in pages.values():
            if 'missing' not in page:
                return {'title':page.get('title',title),'text':str(page.get('extract',''))[:12000],
                        'source_url':'https://en.wikipedia.org/wiki/'+urllib.parse.quote(page.get('title',title).replace(' ','_')),
                        'source_type':'encyclopedia','verified':False}
        return None
