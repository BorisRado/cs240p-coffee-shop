#!/usr/bin/env python3
"""Lab 5, Part 3: three questions about the logs, as DataFrame operations
(Day 5, slides 66-73). Prints the code it runs, then the result.

    python3 queries.py show s3://cs240p-logs-123456789012/logs/
    python3 queries.py 1 s3://cs240p-logs-123456789012/logs/
    python3 queries.py 2 ...
    python3 queries.py 3 ...

Without the second argument it reads the local folder logs/.
"""
import sys
from lake import *

QUERIES = {
    "show": '''logs.show(3)
print(logs.count(), "rows")''',

    "1": '''# Query 1: requests per client, the busiest first
top = logs.groupBy("client_ip").count().orderBy("count", desc=True)
top.explain()
top.show(10)''',

    "2": '''# Query 2: the pages that do not exist (404), the most asked for first
(logs.filter(logs.status == 404)
     .groupBy("path").count()
     .orderBy("count", desc=True)
     .show(10))''',

    "3": '''# Query 3: the three numbers of reduce.py, for the busy clients only
busy = (logs.groupBy("client_ip")
            .agg(requests=count(), errors=avg(logs.status >= 400),
                 paths=countDistinct("path"), agent=mode("agent"))
            .filter(col("requests") > 300))
busy.orderBy("errors", desc=True).show()''',
}

which = sys.argv[1] if len(sys.argv) > 1 else "show"
source = sys.argv[2] if len(sys.argv) > 2 else "logs"
if which not in QUERIES:
    sys.exit(__doc__)
code = QUERIES[which]
print('logs = read_logs("%s")' % source)
print(code)
print()
logs = read_logs(source)
exec(code)
