# Fallback Plan

## Fetch Recent LinkedIn Conversation Threads

Intent: Return LinkedIn Messaging thread URLs, contact names, last-message timestamps, and unread/new status for conversations within the requested day window.

- Confirm Chrome is already logged into LinkedIn.
- Prefer opening `https://www.linkedin.com/feed/` instead of directly opening Messaging, because opening individual Messaging threads can mark messages seen/read.
- From the logged-in LinkedIn page, read `https://www.linkedin.com/voyager/api/me` with the active cookies and CSRF token from the `JSESSIONID` cookie to determine the current `urn:li:fsd_profile:...` mailbox URN.
- Fetch recent conversations through LinkedIn's messaging GraphQL endpoint using the active browser session:
  - Initial request shape: `/voyager/api/voyagerMessagingGraphQL/graphql?queryId=messengerConversations.0d5e6781bbee71c3e51c8843c6519f48&variables=(mailboxUrn:<encoded-self-fsd-profile-urn>)`
  - Older-page request shape: `/voyager/api/voyagerMessagingGraphQL/graphql?queryId=messengerConversations.9501074288a12f3ae9e3c7ea243bccbf&variables=(query:(predicateUnions:List((conversationCategoryPredicate:(category:PRIMARY_INBOX)))),count:20,mailboxUrn:<encoded-self-fsd-profile-urn>,lastUpdatedBefore:<oldest-lastActivityAt>)`
- Use headers `accept: application/vnd.linkedin.normalized+json+2.1`, `csrf-token: <JSESSIONID value>`, and `x-restli-protocol-version: 2.0.0`.
- Parse `included` items whose object has `conversationUrl` and `lastActivityAt`.
- Map `*conversationParticipants` to included `com.linkedin.messenger.MessagingParticipant` objects. Exclude the participant whose `hostIdentityUrn` is the current user's `urn:li:fsd_profile:...`.
- Output `contact_name`, UTC ISO `last_message_date`, `thread_url`, and `new`, where `new` is true if `unreadCount > 0` or `read === false`.
- Stop once the requested `maximum_threads` count is reached, the last-message date is older than `last_message_within_days`, no new conversations are returned, or the safe pagination cap is reached.
- Close any LinkedIn tab opened for the fallback run.

Notes:
- LinkedIn's observed default conversation page size is 20, and its load-more request also used `count:20`.
- Avoid clicking or opening each conversation; that can mark unread messages as read and is more automation-like than the low-volume read request path.
- Avoid rapid repeated requests. Use a small delay between older-page reads and keep the total result cap modest.
