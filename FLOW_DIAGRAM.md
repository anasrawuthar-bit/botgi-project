# 🔄 Customer Feedback System - Flow Diagram

## Customer Journey Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    JOB CREATION                                  │
│  Staff creates job → Receipt printed with QR code               │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                 CUSTOMER RECEIVES RECEIPT                        │
│  Receipt contains:                                               │
│  • Job Code (e.g., BOTGI-250116-001)                           │
│  • QR Code (scan to track)                                      │
│  • Contact details                                               │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              CUSTOMER TRACKS JOB STATUS                          │
│                                                                   │
│  Option 1: Scan QR Code        Option 2: Manual Login           │
│  ├─ Instant access             ├─ Enter job code                │
│  ├─ No typing needed           ├─ Enter phone number            │
│  └─ Direct to status page      └─ View status                   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    JOB STATUS PAGE                               │
│  Shows:                                                          │
│  • Current status (Pending/Repairing/Completed/etc.)            │
│  • Device details                                                │
│  • Technician notes                                              │
│  • Billing breakdown (when ready)                                │
│  • Download bill button (when closed)                            │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  JOB CLOSED BY STAFF                             │
│  Status changes to "Closed"                                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              FEEDBACK FORM APPEARS                               │
│  Customer sees:                                                  │
│  • "Rate Your Experience" section                               │
│  • 5 interactive stars (click to rate)                          │
│  • Optional comment box                                          │
│  • Submit button                                                 │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              CUSTOMER SUBMITS FEEDBACK                           │
│  • Selects star rating (1-5)                                    │
│  • Optionally adds comment                                       │
│  • Clicks "Submit Feedback"                                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                 FEEDBACK SAVED                                   │
│  • Stored in database                                            │
│  • Timestamp recorded                                            │
│  • Thank you message shown                                       │
│  • Cannot submit again                                           │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              STAFF VIEWS FEEDBACK                                │
│                                                                   │
│  Location 1: Job Detail Page                                     │
│  ├─ Shows rating and comment                                     │
│  └─ Visible in right sidebar                                     │
│                                                                   │
│  Location 2: Analytics Dashboard                                 │
│  ├─ Overall statistics                                           │
│  ├─ Technician performance                                       │
│  └─ Recent feedback list                                         │
└─────────────────────────────────────────────────────────────────┘
```

## Staff Analytics Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                  STAFF LOGS IN                                   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              NAVIGATION BAR OPTIONS                              │
│  • Dashboard                                                     │
│  • Reports                                                       │
│  • Feedback ← NEW!                                              │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│           FEEDBACK ANALYTICS DASHBOARD                           │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  OVERALL STATISTICS                                      │   │
│  │  • Total Feedback: 45                                    │   │
│  │  • Average Rating: 4.2 ★                                │   │
│  │  • Rating Distribution:                                  │   │
│  │    5★ ████████████████ 20                              │   │
│  │    4★ ██████████ 15                                     │   │
│  │    3★ ████ 7                                            │   │
│  │    2★ ██ 2                                              │   │
│  │    1★ █ 1                                               │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  TECHNICIAN PERFORMANCE                                  │   │
│  │  ┌──────────┬───────┬────────┬────────────────────┐    │   │
│  │  │ Tech     │ Count │ Avg    │ Performance        │    │   │
│  │  ├──────────┼───────┼────────┼────────────────────┤    │   │
│  │  │ John     │ 20    │ 4.5 ★ │ ████████████ 90%  │    │   │
│  │  │ Sarah    │ 15    │ 4.2 ★ │ ██████████ 84%    │    │   │
│  │  │ Mike     │ 10    │ 3.8 ★ │ ████████ 76%      │    │   │
│  │  └──────────┴───────┴────────┴────────────────────┘    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  RECENT FEEDBACK                                         │   │
│  │  • BOTGI-250116-001 | John Doe | ★★★★★ | "Great!"     │   │
│  │  • BOTGI-250115-045 | Jane S. | ★★★★☆ | "Good work"   │   │
│  │  • BOTGI-250115-044 | Bob M.  | ★★★☆☆ | "Okay"        │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## QR Code Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    QR CODE GENERATION                            │
│  • Unique URL for each job                                       │
│  • Format: https://yoursite.com/qr/BOTGI-250116-001/            │
│  • Generated automatically                                       │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  QR CODE LOCATIONS                               │
│                                                                   │
│  Location 1: Job Receipt (Printed)                              │
│  ├─ Customer receives at job creation                           │
│  └─ Can scan anytime to check status                            │
│                                                                   │
│  Location 2: Staff Job Detail Page                              │
│  ├─ Staff can view/share                                        │
│  └─ Useful for customer support                                 │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              CUSTOMER SCANS QR CODE                              │
│  • Opens camera app                                              │
│  • Points at QR code                                             │
│  • Automatic redirect to job status                             │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              INSTANT JOB STATUS ACCESS                           │
│  • No login required                                             │
│  • No typing needed                                              │
│  • Direct to job information                                     │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow Diagram

```
┌──────────────┐
│   Customer   │
│   Submits    │
│   Feedback   │
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────┐
│  JobTicket Model (Database)          │
│  ├─ feedback_rating: 5               │
│  ├─ feedback_comment: "Great work!"  │
│  └─ feedback_date: 2025-01-16        │
└──────┬───────────────────────────────┘
       │
       ├─────────────────┬─────────────────┐
       │                 │                 │
       ▼                 ▼                 ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ Job Detail  │  │  Analytics  │  │  Job Log    │
│    Page     │  │  Dashboard  │  │   Entry     │
│             │  │             │  │             │
│ Shows:      │  │ Calculates: │  │ Records:    │
│ • Rating    │  │ • Avg       │  │ • Action    │
│ • Comment   │  │ • Count     │  │ • Details   │
│ • Date      │  │ • Tech perf │  │ • User      │
└─────────────┘  └─────────────┘  └─────────────┘
```

## User Interface Flow

```
CLIENT STATUS PAGE (Job Closed)
┌─────────────────────────────────────────────────────────────┐
│  Job Status: CLOSED ✓                                       │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Billing Summary                                     │   │
│  │  • Service: ₹500                                     │   │
│  │  • Parts: ₹1000                                      │   │
│  │  • Total: ₹1500                                      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  ⭐ Rate Your Experience                            │   │
│  │                                                       │   │
│  │  How would you rate our service?                     │   │
│  │  ☆ ☆ ☆ ☆ ☆  (Click to rate)                        │   │
│  │                                                       │   │
│  │  Additional Comments (Optional)                      │   │
│  │  ┌─────────────────────────────────────────────┐   │   │
│  │  │ Share your experience...                     │   │   │
│  │  │                                               │   │   │
│  │  └─────────────────────────────────────────────┘   │   │
│  │                                                       │   │
│  │  [Submit Feedback]                                   │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘

AFTER SUBMISSION
┌─────────────────────────────────────────────────────────────┐
│  ✓ Thank you for your feedback!                             │
│  You rated us: ★★★★★                                       │
└─────────────────────────────────────────────────────────────┘
```

## Integration Points

```
┌─────────────────────────────────────────────────────────────┐
│                    SYSTEM INTEGRATION                        │
│                                                               │
│  Models (models.py)                                          │
│  ├─ JobTicket.feedback_rating                               │
│  ├─ JobTicket.feedback_comment                              │
│  └─ JobTicket.feedback_date                                 │
│                                                               │
│  Views (views.py)                                            │
│  ├─ client_status() - Handles feedback submission           │
│  ├─ qr_access() - QR code redirect                          │
│  ├─ feedback_analytics() - Analytics dashboard              │
│  └─ staff_job_detail() - Shows feedback & QR                │
│                                                               │
│  Forms (forms.py)                                            │
│  └─ FeedbackForm - Star rating + comment                    │
│                                                               │
│  URLs (urls.py)                                              │
│  ├─ /qr/<job_code>/ - QR access                            │
│  └─ /staff/feedback-analytics/ - Analytics                  │
│                                                               │
│  Templates                                                   │
│  ├─ client_status.html - Feedback form                      │
│  ├─ staff_job_detail.html - Feedback display + QR           │
│  ├─ feedback_analytics.html - Analytics dashboard           │
│  └─ job_creation_receipt_print.html - QR on receipt         │
└─────────────────────────────────────────────────────────────┘
```

---

**Legend:**
- ▼ = Flow direction
- ├─ = Branch/Option
- └─ = End of branch
- ★ = Filled star (rating)
- ☆ = Empty star
- █ = Progress bar fill
- ✓ = Completed/Success
