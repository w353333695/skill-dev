curl -X POST "http://127.0.0.1:8079/v3/object/USER/instance/_search" \
-H "Content-Type: application/json" \
-H "org: 1023" -H "user: defaultUser" \
-d '{                                                                                                            
  "query": {  
    "name": "aaa"
  },
  "fields": ["*"],
  "page": 1,
  "page_size": 100
}'