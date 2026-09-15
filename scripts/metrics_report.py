"""Print the privacy-preserving product measurement ledger as JSON."""
import argparse
import json
from pathlib import Path
from app import metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=metrics.DB)
    parser.add_argument('--start', type=float)
    parser.add_argument('--end', type=float)
    parser.add_argument('--write-rollup', action='store_true')
    args = parser.parse_args()
    if args.write_rollup:
        metrics.rollup(args.db, args.start, args.end)
    output = {'events': metrics.report(args.db, args.start, args.end)}
    # The product ledger is the source for actual generation cost.  The report
    # exposes only aggregates, never user IDs, prompts, or image paths.
    try:
        import sqlite3
        with sqlite3.connect(args.db) as db:
            clauses=[];values=[]
            if args.start is not None: clauses.append('c.created>=?');values.append(args.start)
            if args.end is not None: clauses.append('c.created<?');values.append(args.end)
            where=(' WHERE '+' AND '.join(clauses)) if clauses else ''
            output['consumption']=[dict(zip(['plan','kind','status','calls','cost_usd','payer'], row)) for row in db.execute(
                "SELECT COALESCE(m.plan,'free'),c.kind,c.status,COUNT(*),COALESCE(SUM(c.cost_usd),0),c.payer "
                "FROM consumption c LEFT JOIN memberships m ON m.user=c.user"+where+
                " GROUP BY COALESCE(m.plan,'free'),c.kind,c.status,c.payer ORDER BY 1,2,3", values)]
    except (sqlite3.OperationalError, FileNotFoundError):
        output['consumption']=[]
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
