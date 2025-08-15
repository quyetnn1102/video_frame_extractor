# 🔄 Git Author Change Guide

Complete guide for changing author information in git commits to match your GitHub username.

## 📋 Overview

This guide covers how to:
- Change commit author information from corporate email to personal GitHub account
- Rewrite git history safely
- Clean up after the operation
- Push changes to GitHub

## 🎯 Use Cases

### When to Use This Guide
- ✅ You committed with a corporate email but want to use your personal GitHub account
- ✅ You want to match your GitHub username in commit history
- ✅ You need to change author information across all commits
- ✅ You want a clean, consistent commit history

### When NOT to Use This Guide
- ❌ On repositories with multiple contributors (can mess up their commits)
- ❌ On public repositories that others have already cloned
- ❌ If you only want to change future commits (just update git config instead)

## 🚨 Important Warnings

> ⚠️ **WARNING**: This process rewrites git history and will change commit hashes!
> 
> - Only do this on repositories you own
> - Inform collaborators before doing this
> - Make a backup of your repository first
> - Use `--force` push carefully

## 📝 Step-by-Step Instructions

### Step 1: Check Current Author Information

```powershell
# View current commit history with author details
git log --format="%h %an <%ae> %s"
```

**Expected Output:**
```
e4f9b2b Quyet Nguyen Ngoc <quyetnn@fpt.com> docs: Add comprehensive README
a7be531 Quyet Nguyen Ngoc <quyetnn@fpt.com> Add GitHub setup guide  
0b19989 Quyet Nguyen Ngoc <quyetnn@fpt.com> Initial commit: VideoExtract tool
```

### Step 2: Backup Your Repository (Optional but Recommended)

```powershell
# Create a backup branch
git branch backup-before-author-change

# Or create a complete backup folder
cd ..
cp -r video_frame_extractor video_frame_extractor_backup
```

### Step 3: Rewrite Commit History

Replace the email addresses and names in the command below:

```powershell
git filter-branch --env-filter '
if [ "$GIT_AUTHOR_EMAIL" = "OLD_EMAIL@DOMAIN.com" ]; then 
    export GIT_AUTHOR_NAME="NEW_USERNAME"
    export GIT_AUTHOR_EMAIL="NEW_EMAIL@users.noreply.github.com"
fi
if [ "$GIT_COMMITTER_EMAIL" = "OLD_EMAIL@DOMAIN.com" ]; then 
    export GIT_COMMITTER_NAME="NEW_USERNAME"
    export GIT_COMMITTER_EMAIL="NEW_EMAIL@users.noreply.github.com"
fi' -- --all
```

**Example (from our case):**
```powershell
git filter-branch --env-filter '
if [ "$GIT_AUTHOR_EMAIL" = "quyetnn@fpt.com" ]; then 
    export GIT_AUTHOR_NAME="quyetnn1102"
    export GIT_AUTHOR_EMAIL="quyetnn1102@users.noreply.github.com"
fi
if [ "$GIT_COMMITTER_EMAIL" = "quyetnn@fpt.com" ]; then 
    export GIT_COMMITTER_NAME="quyetnn1102"
    export GIT_COMMITTER_EMAIL="quyetnn1102@users.noreply.github.com"
fi' -- --all
```

### Step 4: Verify Changes

```powershell
# Check that author information has been updated
git log --format="%h %an <%ae> %s"
```

**Expected Output After Change:**
```
e274b18 quyetnn1102 <quyetnn1102@users.noreply.github.com> docs: Add comprehensive README
626f14b quyetnn1102 <quyetnn1102@users.noreply.github.com> Add GitHub setup guide
10040fe quyetnn1102 <quyetnn1102@users.noreply.github.com> Initial commit: VideoExtract tool
```

### Step 5: Update Remote Repository

#### Option A: Force Push (if you own the repository)
```powershell
# Force push to update GitHub with new history
git push --force origin master
```

#### Option B: Force Push with Lease (safer)
```powershell
# Safer force push (fails if someone else pushed)
git push --force-with-lease origin master
```

### Step 6: Clean Up Backup References

```powershell
# Remove backup references created by filter-branch
git update-ref -d refs/original/refs/heads/master
git update-ref -d refs/original/refs/remotes/origin/master

# Clean up reflog and garbage collect
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### Step 7: Verify Final State

```powershell
# Check final commit history
git log --oneline --graph --all

# Verify no backup references remain
git for-each-ref refs/original/
```

## 📧 Email Address Options

### GitHub Email Options

1. **Public Email**: `your-username@users.noreply.github.com`
   - ✅ Links to your GitHub profile
   - ✅ Keeps email private
   - ✅ Recommended for most users

2. **Personal Email**: `your-email@domain.com`
   - ✅ Uses your real email
   - ❌ Email will be public in git history
   - ❌ Must be added to your GitHub account

3. **GitHub No-Reply**: `noreply@github.com`
   - ❌ Won't link to your profile
   - ❌ Not recommended

## 🛠️ Troubleshooting

### Issue: "WARNING: git-filter-branch has a glut of gotchas"

**Solution**: This is just a warning. You can:
- Continue with the operation (it's safe for our use case)
- Or set `FILTER_BRANCH_SQUELCH_WARNING=1` to suppress the warning

```powershell
$env:FILTER_BRANCH_SQUELCH_WARNING=1
# Then run the filter-branch command
```

### Issue: "failed to push some refs" when force pushing

**Solution**: Use regular force push:
```powershell
git push --force origin master
```

### Issue: Want to change only specific commits

**Solution**: Use interactive rebase instead:
```powershell
git rebase -i HEAD~3  # For last 3 commits
# Then use 'edit' for commits you want to change
# For each commit:
git commit --amend --author="New Name <new-email@domain.com>"
git rebase --continue
```

### Issue: Multiple branches need updating

**Solution**: The `--all` flag in filter-branch handles all branches:
```powershell
# This updates all branches and tags
git filter-branch --env-filter '...' -- --all
```

## 🔍 Alternative Methods

### Method 1: git-filter-repo (Modern Alternative)

Install git-filter-repo and use:
```bash
git filter-repo --mailmap <(echo "New Name <new@email.com> <old@email.com>")
```

### Method 2: BFG Repo-Cleaner

For very large repositories:
```bash
java -jar bfg.jar --strip-blobs-bigger-than 100M
```

### Method 3: Interactive Rebase (For Few Commits)

```powershell
git rebase -i HEAD~N  # N = number of commits to change
# Use 'edit' for commits to modify
# For each: git commit --amend --author="Name <email>"
```

## 📋 Quick Reference Commands

```powershell
# Check current authors
git log --format="%h %an <%ae> %s"

# Rewrite history (replace OLD_EMAIL and NEW_INFO)
git filter-branch --env-filter 'if [ "$GIT_AUTHOR_EMAIL" = "OLD_EMAIL" ]; then export GIT_AUTHOR_NAME="NEW_NAME"; export GIT_AUTHOR_EMAIL="NEW_EMAIL"; fi; if [ "$GIT_COMMITTER_EMAIL" = "OLD_EMAIL" ]; then export GIT_COMMITTER_NAME="NEW_NAME"; export GIT_COMMITTER_EMAIL="NEW_EMAIL"; fi' -- --all

# Force push changes
git push --force origin master

# Clean up
git update-ref -d refs/original/refs/heads/master
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

## ✅ Success Checklist

- [ ] Verified current author information with `git log`
- [ ] Created backup of repository (optional)
- [ ] Ran filter-branch command with correct old/new email addresses
- [ ] Verified changes with `git log --format="%h %an <%ae> %s"`
- [ ] Successfully force-pushed to GitHub
- [ ] Cleaned up backup references
- [ ] Verified final state with `git log --oneline --graph --all`
- [ ] Confirmed GitHub repository shows correct author

## 🎯 Best Practices

1. **Always backup** before rewriting history
2. **Test on a clone** first if unsure
3. **Use GitHub no-reply emails** to maintain privacy
4. **Coordinate with team** if repository has collaborators
5. **Document the change** in your team/project notes
6. **Update local git config** to prevent future issues:

```powershell
git config --global user.name "quyetnn1102"
git config --global user.email "quyetnn1102@users.noreply.github.com"
```

## 📞 Support

If you encounter issues:
1. Check the troubleshooting section above
2. Verify your git configuration: `git config --list | grep user`
3. Ensure you have write access to the repository
4. Create a GitHub issue if problems persist

---

**Created**: August 15, 2025  
**Last Updated**: August 15, 2025  
**Tested On**: Windows PowerShell, Git 2.x

> 💡 **Tip**: Save this guide for future use when setting up new repositories or cleaning up commit history!
