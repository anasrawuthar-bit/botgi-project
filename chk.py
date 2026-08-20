import re
f = open('c:/Users/ANAS/Desktop/botgi_project/job_tickets/templates/job_tickets/reports_dashboard.html', 'rb')
d = f.read().decode('utf-8', 'replace')
f.close()
for m in re.finditer(r'(monthly_net_profit|monthly_total_income|overall_revenue|overall_profit|discount)', d):
    line_no = d[:m.start()].count('\n') + 1
    start = max(0, m.start()-60)
    end = min(len(d), m.end()+60)
    print(f'Line {line_no}: {d[start:end].strip()}')
    print('---')
