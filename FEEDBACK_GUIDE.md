# Quick Reference Guide - Customer Feedback System

## 🎯 What's New?

### 1. Customer Feedback After Job Closure
- Customers can now rate their experience (1-10 score)
- Optional comment field for detailed feedback
- Appears automatically when job status is "Closed"

### 2. QR Code Access
- Every job now has a unique QR code
- Customers scan to view job status instantly
- No need to enter job code or phone number manually
- QR code printed on job creation receipt

### 3. Feedback Analytics Dashboard
- View all customer feedback in one place
- See average ratings and distribution
- Track technician performance
- Identify areas for improvement

## 📱 How Customers Use It

### Viewing Job Status (Traditional Way):
1. Go to website
2. Click "Track Job Status"
3. Enter Job Code + Phone Number
4. View status

### Viewing Job Status (QR Code Way):
1. Scan QR code from receipt
2. Instantly see job status
3. No login required!

### Submitting Feedback:
1. When job is closed, visit job status page
2. See "Rate Your Experience" section
3. Click on numbers (1-10) to rate
4. Optionally add comments
5. Click "Submit Feedback"
6. Done! Thank you message appears

## 👨‍💼 How Staff Use It

### Viewing Feedback on Job Detail:
1. Open any job from dashboard
2. Scroll to right sidebar
3. See "Customer Feedback" section (if submitted)
4. View rating and comments

### Accessing Analytics Dashboard:
1. From staff dashboard, navigate to Reports
2. Click "Feedback Analytics" (or visit `/staff/feedback-analytics/`)
3. View:
   - Total feedback count
   - Average rating
   - Rating distribution chart
   - Technician performance table
   - Recent feedback list

### Sharing QR Code:
1. Open job detail page
2. Scroll to "QR Code Access" section
3. QR code is automatically displayed
4. Customer can scan this anytime
5. Also printed on job creation receipt

## 🔧 Technical Details

### Database Fields Added:
- `feedback_rating` - Integer (1-10)
- `feedback_comment` - Text
- `feedback_date` - DateTime

### New URLs:
- `/qr/<job_code>/` - QR code direct access
- `/staff/feedback-analytics/` - Analytics dashboard

### Files Modified:
- `models.py` - Added feedback fields
- `views.py` - Added feedback submission and analytics views
- `forms.py` - Added FeedbackForm
- `urls.py` - Added new routes
- `client_status.html` - Added feedback form
- `staff_job_detail.html` - Added feedback display and QR code
- `job_creation_receipt_print.html` - Added QR code
- `feedback_analytics.html` - New analytics dashboard

## 💡 Tips

### For Staff:
- Check feedback regularly to improve service
- Use analytics to identify top-performing technicians
- Address negative feedback promptly
- Share QR codes with customers for easy tracking

### For Customers:
- Keep your receipt with QR code safe
- Scan QR code anytime to check status
- Provide honest feedback to help us improve
- Feedback can only be submitted once per job

## 🚀 Testing Checklist

- [ ] Close a job and verify feedback form appears
- [ ] Submit feedback with rating and comment
- [ ] Verify feedback shows in job detail page
- [ ] Access feedback analytics dashboard
- [ ] Scan QR code from receipt
- [ ] Verify QR code redirects to job status
- [ ] Check technician performance metrics
- [ ] Test on mobile device

## 📊 Metrics to Track

- **Response Rate**: % of closed jobs with feedback
- **Average Rating**: Overall customer satisfaction
- **Technician Ratings**: Individual performance
- **Common Issues**: Analyze negative feedback comments
- **Improvement Trends**: Track ratings over time

## 🎨 Customization Options

Want to customize? You can:
- Change rating button colors in CSS
- Modify rating scale (currently 1-10)
- Add more feedback questions
- Customize QR code size/style
- Add email notifications for feedback
- Export feedback data to Excel

## ❓ FAQ

**Q: Can customers change their feedback?**
A: No, feedback can only be submitted once per job.

**Q: Do customers need to login to give feedback?**
A: No, they can access via QR code or traditional login.

**Q: Where is feedback stored?**
A: In the JobTicket model in the database.

**Q: Can I delete feedback?**
A: Yes, staff can access database to modify if needed.

**Q: Does feedback affect technician pay?**
A: That's up to management - the system just tracks it.

## 🔐 Security Notes

- QR codes are public but only show job status
- No sensitive billing info in QR access
- Feedback is anonymous (no user account required)
- Staff-only access to analytics dashboard

## 📞 Support

If you encounter any issues:
1. Check Django logs for errors
2. Verify migrations are applied
3. Clear browser cache
4. Test in incognito mode
5. Contact developer if problem persists

---

**Version**: 1.0
**Last Updated**: 2025
**Developer**: Amazon Q
