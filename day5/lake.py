#!/usr/bin/env python3
"""Lab 5: a very small DataFrame library, in the style of Spark's
structured API (Day 5, slides 66-73). Standard library only.

    from lake import *
    logs = read_logs("s3://cs240p-logs-123456789012/logs/")   # or "logs"
    (logs.filter(logs.status == 404)
         .groupBy("path").count()
         .orderBy("count", desc=True).show(10))

A DataFrame is a table of Rows with named columns (slide 67). Every
operation returns a new DataFrame and adds a step to its plan; nothing
runs until show(), collect() or count() (slide 71). explain() prints the
plan. Spark does the same, on a cluster; this runs in your CloudShell.
"""
import os
import re
import subprocess
from collections import Counter

AGENTS = [("CoffeeApp", "CoffeeApp"), ("UptimeMonitor", "UptimeMonitor"),
          ("zgrab", "zgrab"), ("python-requests", "python-requests"),
          ("Nmap", "Nmap"), ("Firefox", "Firefox"), ("Chrome", "Chrome"),
          ("Safari", "Safari")]


def agent_name(user_agent):
    for word, name in AGENTS:
        if word in user_agent:
            return name
    return "other"


class Row(dict):
    """One row: a dict whose columns can also be read as r.status."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


class Cond:
    """A condition on a row, with its text for the plan."""
    def __init__(self, text, fn):
        self.text, self.fn = text, fn

    def __call__(self, row):
        return self.fn(row)


class Column:
    """A column by name. Comparing it gives a condition: logs.status == 404."""
    def __init__(self, name):
        self.name = name

    def _cmp(self, op, other, fn):
        name = self.name
        return Cond("%s %s %r" % (name, op, other),
                    lambda row: fn(row[name], other))

    def __eq__(self, o): return self._cmp("==", o, lambda a, b: a == b)
    def __ne__(self, o): return self._cmp("!=", o, lambda a, b: a != b)
    def __gt__(self, o): return self._cmp(">", o, lambda a, b: a > b)
    def __ge__(self, o): return self._cmp(">=", o, lambda a, b: a >= b)
    def __lt__(self, o): return self._cmp("<", o, lambda a, b: a < b)
    def __le__(self, o): return self._cmp("<=", o, lambda a, b: a <= b)
    __hash__ = None


def col(name):
    return Column(name)


class Agg:
    """An aggregation over the rows of one group."""
    def __init__(self, text, fn):
        self.text, self.fn = text, fn


def count():
    return Agg("count()", lambda rows: len(rows))


def countDistinct(name):
    return Agg("countDistinct(%s)" % name,
               lambda rows: len(set(r[name] for r in rows)))


def avg(what):
    """Average of a column, or the share of rows for which a condition holds."""
    if isinstance(what, Cond):
        return Agg("avg(%s)" % what.text, lambda rows: round(
            sum(1 for r in rows if what(r)) / len(rows), 2))
    return Agg("avg(%s)" % what, lambda rows: round(
        sum(r[what] for r in rows) / len(rows), 2))


def mode(name):
    """The most common value of a column in the group."""
    return Agg("mode(%s)" % name, lambda rows: Counter(
        r[name] for r in rows).most_common(1)[0][0])


class DataFrame:
    def __init__(self, source, name, steps=()):
        self._source, self._name, self._steps = source, name, list(steps)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return Column(name)                     # logs.status

    def _add(self, text, fn):
        return DataFrame(self._source, self._name, self._steps + [(text, fn)])

    def filter(self, cond):
        return self._add("filter(%s)" % cond.text,
                         lambda rows: [r for r in rows if cond(r)])

    where = filter

    def select(self, *names):
        return self._add("select(%s)" % ", ".join(names),
                         lambda rows: [Row((n, r[n]) for n in names)
                                       for r in rows])

    def groupBy(self, name):
        return GroupedData(self, name)

    def orderBy(self, name, desc=False):
        return self._add("orderBy(%s%s)" % (name, " desc" if desc else ""),
                         lambda rows: sorted(rows, key=lambda r: r[name],
                                             reverse=desc))

    def limit(self, n):
        return self._add("limit(%d)" % n, lambda rows: rows[:n])

    def collect(self):
        """Run the plan: read the source, then apply each step in order."""
        rows = self._source()
        for text, fn in self._steps:
            rows = fn(rows)
        return rows

    def count(self):
        return len(self.collect())

    def explain(self):
        print("== Plan ==")
        for i, text in enumerate(["read %s" % self._name]
                                 + [t for t, _ in self._steps]):
            print("  " * i + text)

    def show(self, n=20):
        rows = self.collect()
        head = rows[:n]
        if not head:
            print("(no rows)")
            return
        names = list(head[0].keys())
        cells = [[str(r[c]) for c in names] for r in head]
        width = [max(len(c), *(len(row[i]) for row in cells))
                 for i, c in enumerate(names)]
        line = "+" + "+".join("-" * w for w in width) + "+"
        print(line)
        print("|" + "|".join(c.rjust(w) for c, w in zip(names, width)) + "|")
        print(line)
        for row in cells:
            print("|" + "|".join(v.rjust(w) for v, w in zip(row, width)) + "|")
        print(line)
        if len(rows) > n:
            print("only showing top %d of %d rows" % (n, len(rows)))


class GroupedData:
    def __init__(self, df, name):
        self.df, self.name = df, name

    def _groups(self, rows):
        groups = {}
        for r in rows:
            groups.setdefault(r[self.name], []).append(r)
        return groups

    def count(self):
        key = self.name
        return self.df._add("groupBy(%s).count()" % key, lambda rows: [
            Row({key: k, "count": len(g)})
            for k, g in self._groups(rows).items()])

    def agg(self, **aggs):
        key = self.name
        text = "groupBy(%s).agg(%s)" % (key, ", ".join(
            "%s=%s" % (c, a.text) for c, a in aggs.items()))
        return self.df._add(text, lambda rows: [
            Row([(key, k)] + [(c, a.fn(g)) for c, a in aggs.items()])
            for k, g in self._groups(rows).items()])


def read_logs(path):
    """A DataFrame of load-balancer log lines: one Row per request, with
    the columns time, client_ip, status, verb, path and agent. The path
    is a local folder, or s3://bucket/folder/ (fetched once, into
    lake-cache/). Numbers in the path are replaced by N, as in map.py."""
    if path.startswith("s3://"):
        folder = "lake-cache"
        if not (os.path.isdir(folder) and os.listdir(folder)):
            subprocess.run(["aws", "s3", "cp", path, folder, "--recursive",
                            "--only-show-errors"], check=True)
    else:
        folder = path
    files = sorted(f for f in os.listdir(folder) if f.endswith(".log"))

    def source():
        rows = []
        for name in files:
            for line in open(os.path.join(folder, name)):
                f = line.split(" ")
                if len(f) < 12 or f[0] not in ("http", "https"):
                    continue
                q = line.split('"')
                verb, url = q[1].split(" ")[:2]
                p = "/" + url.split("/", 3)[3] if url.count("/") >= 3 else "/"
                rows.append(Row(time=f[1][11:19], client_ip=f[3].rsplit(":", 1)[0],
                                status=int(f[8]), verb=verb,
                                path=re.sub(r"[0-9]+", "N", p),
                                agent=agent_name(q[3])))
        return rows
    return DataFrame(source, path)
