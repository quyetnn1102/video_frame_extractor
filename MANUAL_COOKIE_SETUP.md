# Manual Instagram Cookie Setup Guide

When automatic cookie extraction fails due to browser security restrictions, you can manually export and use Instagram cookies for age-restricted content.

## 🍪 Step-by-Step Manual Cookie Setup

### Method 1: Using Browser Extension (Recommended)

#### For Chrome Users:
1. **Install Cookie Extension**
   - Go to Chrome Web Store
   - Search for "Export Cookies" or "Get cookies.txt"
   - Install a reputable cookie export extension

2. **Login to Instagram**
   - Open Instagram in your browser
   - Make sure you're logged in
   - Navigate to the video you want to download
   - Verify you can view the age-restricted content

3. **Export Cookies**
   - Click the cookie extension icon
   - Select "Export cookies for this site" or "instagram.com"
   - Choose "Netscape format" or "cookies.txt format"
   - Save the file

4. **Place Cookie File**
   - Rename the downloaded file to `instagram_cookies.txt`
   - Place it in your video_frame_extractor folder
   - The file should be in the same directory as `app.py`

### Method 2: Manual Browser Export

#### Chrome Developer Tools Method:
1. **Open Developer Tools**
   - Press F12 or Ctrl+Shift+I
   - Go to Instagram.com and login
   - Navigate to Application/Storage tab
   - Click on "Cookies" → "https://www.instagram.com"

2. **Export Cookie Data**
   - Right-click in the cookie list
   - Select "Export" or copy all cookies
   - Format should be: `name=value; Domain=.instagram.com; Path=/`

3. **Create Cookie File**
   - Create a text file named `instagram_cookies.txt`
   - Add cookies in Netscape format:
   ```
   # Netscape HTTP Cookie File
   .instagram.com	TRUE	/	FALSE	1735689600	sessionid	YOUR_SESSION_ID
   .instagram.com	TRUE	/	FALSE	1735689600	csrftoken	YOUR_CSRF_TOKEN
   ```

## 🔍 Cookie File Format

Your `instagram_cookies.txt` should look like this:
```
# Netscape HTTP Cookie File
# This is a generated file!  Do not edit.

.instagram.com	TRUE	/	FALSE	1735689600	sessionid	54321%3A1234567890%3A28%3AAYeG...
.instagram.com	TRUE	/	FALSE	1735689600	csrftoken	abcd1234567890efghij...
.instagram.com	TRUE	/	FALSE	1735689600	mid	XYZ123...
.instagram.com	TRUE	/	FALSE	1735689600	ig_did	12345678-1234-1234-1234-123456789012
```

## 📂 File Placement

```
video_frame_extractor/
├── app.py
├── instagram_cookies.txt  ← Place your cookie file here
├── templates/
├── downloads/
└── ...
```

## ✅ Testing Your Setup

1. **Place the cookie file** in the correct location
2. **Restart the application** if it's currently running
3. **Try the Instagram URL** again
4. **Check the console output** for "Trying manual cookie file..."

If successful, you'll see:
```
Trying manual cookie file...
Success with manual cookie file!
```

## 🛠️ Troubleshooting

### ❌ Cookie File Not Found
**Error**: No "Trying manual cookie file..." message
**Solution**: 
- Verify file is named exactly `instagram_cookies.txt`
- Ensure it's in the same directory as `app.py`
- Check file permissions (should be readable)

### ❌ Cookie Format Error
**Error**: "Invalid cookie format" or authentication still fails
**Solution**:
- Ensure cookies are in Netscape format
- Verify sessionid and csrftoken are present
- Make sure cookies are from the same browser session where you can view the content

### ❌ Expired Cookies
**Error**: Authentication works initially then fails later
**Solution**:
- Instagram cookies expire regularly
- Re-export cookies when they stop working
- Keep your browser session active on Instagram

### ❌ Still Getting Age Restriction
**Error**: Still shows "Restricted Video" even with cookies
**Solution**:
- Verify you can view the content in your browser with the same account
- Check that the cookies are from the correct Instagram session
- Try logging out and back into Instagram, then re-export cookies

## 🔒 Security Notes

### ⚠️ Important Security Warnings:
- **Never share your cookie file** - it contains your login session
- **Keep the file secure** - treat it like a password
- **Delete old cookie files** when no longer needed
- **Don't commit cookie files to version control**

### 🛡️ Best Practices:
- Export cookies only when needed for specific content
- Use a dedicated browser profile for content downloading
- Regularly clean up old cookie files
- Monitor for unusual Instagram account activity

## 🔄 Cookie Refresh Workflow

For regular use with age-restricted content:

1. **Weekly Cookie Refresh**
   - Export new cookies weekly
   - Replace the old `instagram_cookies.txt`
   - Test with a known age-restricted video

2. **Automated Checks**
   - The app will automatically try manual cookies first
   - Falls back to browser extraction if manual cookies fail
   - Provides clear error messages for debugging

3. **Maintenance**
   - Delete old cookie files
   - Keep browser logged into Instagram
   - Monitor application logs for authentication issues

## 📞 Need Help?

If you're still having issues:

1. **Check the application logs** for specific error messages
2. **Verify cookie file format** matches the examples above
3. **Test with public Instagram content first** to ensure basic functionality
4. **Try alternative platforms** (YouTube, TikTok) if Instagram continues to fail

## 🎯 Success Indicators

You'll know the manual cookie setup is working when:
- ✅ Console shows "Trying manual cookie file..."
- ✅ Console shows "Success with manual cookie file!"
- ✅ Age-restricted content downloads successfully
- ✅ No "Restricted Video" errors for content you can view in browser

Remember: Manual cookies are a fallback solution for when browser security prevents automatic extraction. For most public content, the automatic system should work without requiring manual setup.
