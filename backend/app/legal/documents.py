"""Launch-ready legal documents.

Every statement here describes behaviour that exists in this codebase today.
Where a capability is absent, the document says it is absent rather than
omitting the subject - a policy that is silent about crash reporting reads as if
crash reporting happens.

Deliberately not claimed anywhere: that wellness check-ins are medical records,
HIPAA compliance, GDPR certification, or encryption the service does not have.
"""

from __future__ import annotations

from app.legal.operator import OperatorIdentity

LAST_UPDATED = "12 September 2026"


def privacy_policy(operator: OperatorIdentity) -> str:
    return f"""
<p class="meta">Last updated: {LAST_UPDATED}</p>

<p>This service is operated by {operator.display_operator}. It is not operated
by a company, and there is no corporate entity behind it at this time. If that
changes, this page will be updated before the change takes effect.</p>

<h2>What this app records</h2>
<ul>
  <li><strong>Your check-in.</strong> The goal you pick and the numbers you
      report for stress, energy, mental activity, sleepiness, along with how
      much time you have and how experienced you are.</li>
  <li><strong>Your sessions.</strong> Which practice was recommended, how long
      it ran, and whether you finished it.</li>
  <li><strong>Your feedback.</strong> How you rated the session afterwards, the
      after-session numbers you report, and an optional free-text note.</li>
  <li><strong>What happened during a session.</strong> Which part you reached,
      when you paused, whether something interrupted it, and whether you
      finished. This is how a session you were interrupted during can be picked
      up where you left it.</li>
  <li><strong>A pseudonymous identifier.</strong> A random value generated on
      your device the first time you use the app.</li>
</ul>

<h2>The identifier, specifically</h2>
<p>It is a randomly generated UUID created on your device and stored in your
device's secure storage - the Keychain on iOS, Keystore-backed storage on
Android. It is <em>not</em> derived from your device. It is not your advertising
ID, not your IDFA or IDFV, not your IMEI, not your MAC address, and not a
fingerprint of your hardware.</p>
<p>It exists for one reason: so your own history can be found, exported and
deleted without asking you to create an account.</p>

<h2>What this app does not collect</h2>
<p>No name. No email address. No phone number. No location. No camera or
microphone access. No contacts. No advertising identifier. No health data from
Apple Health or Health Connect - those integrations do not exist in this
version.</p>
<p>Nothing you say or do out loud is recorded. The app speaks; it never
listens.</p>

<h2>Spoken guidance</h2>
<p>Sessions are spoken by your own device, using the text-to-speech voice built
into it. The words are written by us and are the same for everyone. No
identifier, no session, no history and nothing you have typed is ever sent to a
speech service - the request is the sentence and the voice to read it with.</p>
<p>One thing worth saying plainly, because we cannot see it and will not pretend
otherwise: <strong>on Android, the system's own text-to-speech engine may
perform synthesis over the network</strong>, depending on the engine and voice
you have configured. That happens inside Android, outside this app, and the app
has no way to observe it. Your device's text-to-speech settings control it.</p>

<h2>Playing in the background</h2>
<p>A session keeps playing when you lock your phone or switch apps, because a
meditation you have to watch a screen for is not much of a meditation. That
permission does one thing - it lets the audio continue - and it collects
nothing.</p>
<p>If your headphones disconnect mid-session, playback pauses instead of
switching to the speaker. That is deliberate: what you are listening to is
nobody else's business.</p>

<h2>Why it is collected</h2>
<p>To choose a practice that fits the state you reported, to show you your own
history, and to understand in aggregate whether the recommendations are helping.
That is the complete list of purposes.</p>

<h2>Automated decision-making</h2>
<p>The practice you are offered is chosen by a deterministic rules engine from
the numbers you enter. It is not chosen by a machine-learning model, and no
generative AI is involved in selecting it. The same inputs always produce the
same recommendation.</p>

<h2>Sharing</h2>
<p>Your data is not sold, not shared with advertisers, and not used for
advertising of any kind. It is not shared with a data broker. No third-party
analytics, attribution or advertising software is present in the app.</p>

<h2>Who processes it</h2>
<p>The service runs on infrastructure provided by Oracle Cloud Infrastructure,
which hosts the application and its database. That is the only subprocessor. The
current list is published in the repository at
<code>compliance/subprocessors.v1.yaml</code>.</p>

<h2>How long it is kept</h2>
<p>Your check-ins, sessions and feedback are kept until you delete them. There
is no automatic expiry, because the history is the feature. Operational server
logs are kept for 30 days and contain request identifiers and status codes - not
your identifier, not your check-in values and not your notes. Exports are
generated when you ask for one and are not stored.</p>

<h2>Deleting your data</h2>
<p>Open <strong>Your sessions</strong> in the app and choose
<strong>Delete my meditation data</strong>. This permanently removes your
check-ins, sessions, feedback and any experiment assignment from the service, and
your device then starts with a new identifier. It is immediate, it is a real
deletion rather than a hidden flag, and there is no waiting period.</p>

<h2>Exporting your data</h2>
<p>The same screen offers <strong>Export my meditation data</strong>, which
returns everything stored against your identifier as JSON.</p>

<h2>Security</h2>
<p>Traffic between the app and the service uses HTTPS. The identifier is held in
your device's secure storage. Data is stored in a managed PostgreSQL database
with access restricted to the operator.</p>
<p>What is <em>not</em> claimed: this service has not had an independent
security audit, is not HIPAA compliant, is not certified under any privacy
framework, and does not apply end-to-end encryption to your session content.</p>

<h2>International processing</h2>
<p>The service is hosted in a single cloud region. If you use the app from
another country, your data is processed in that region.</p>

<h2>Children</h2>
<p>This app is intended for adults. It is not designed for or marketed to
children, is not in a Kids category, and does not knowingly collect data from
children.</p>

<h2>Wellness, not healthcare</h2>
<p>The information you enter is self-reported wellbeing data. It is not a
medical record, it is not reviewed by a clinician, and it is not used to
diagnose or treat anything.</p>

<h2>Contact</h2>
<p>Questions about this policy: <strong>{operator.contact_email}</strong>.</p>

<h2>Changes</h2>
<p>If this policy changes, the date at the top changes with it and the updated
version is published here before the change takes effect.</p>
"""


def privacy_choices(operator: OperatorIdentity) -> str:
    return f"""
<p class="meta">Last updated: {LAST_UPDATED}</p>

<p>Everything on this page works without an account and without agreeing to
anything.</p>

<h2>Export your meditation data</h2>
<p>In the app: <strong>Your sessions</strong> &rarr; <strong>Export my
meditation data</strong>. You receive a JSON file containing your check-ins,
recommendations, sessions, feedback and experiment assignments. Nothing is
emailed and no copy is retained.</p>

<h2>Delete your meditation data</h2>
<p>In the app: <strong>Your sessions</strong> &rarr; <strong>Delete my
meditation data</strong>. One confirmation, then everything stored against your
identifier is permanently removed and your device starts fresh with a new one.
There is no retention option to opt out of and no grace period during which it
is recoverable.</p>

<h2>Your identifier</h2>
<p>You are identified to this service only by a random UUID generated on your
device. It is not linked to your name, your email, your device or any
advertising identifier. Deleting your data replaces it; uninstalling the app
removes it from your device.</p>
<p>Because the identifier is the only key to your data, deleting the app without
deleting your data first leaves that data on the service with no way for you -
or us - to connect it to you again.</p>

<h2>Analytics</h2>
<p>There is no third-party analytics software in this app. The service records
which practices were recommended and how sessions were rated, in order to
evaluate whether the recommendations work. That analysis is aggregate and runs
offline; it never feeds back automatically into what you are offered.</p>

<h2>Tracking and advertising</h2>
<p>This app does not track you. Your data is never combined with data from other
companies' apps or websites, and there is no advertising in the product.</p>

<h2>Accounts</h2>
<p>This version has no accounts, so there is nothing to sign into and nothing to
close. If accounts are added later, in-app account deletion will ship at the
same time, not afterwards.</p>

<h2>Contact</h2>
<p>{operator.contact_email}</p>
"""


def terms_of_use(operator: OperatorIdentity) -> str:
    return f"""
<p class="meta">Last updated: {LAST_UPDATED}</p>

<p>These terms govern your use of this mindfulness and meditation application,
operated by {operator.display_operator}.</p>

<h2>1. What this service is</h2>
<p>A wellness and mindfulness product. It suggests a meditation practice based
on how you say you are feeling, and guides you through it.</p>

<h2>2. What it is not</h2>
<p>It is not a medical device, not a healthcare service, and not a substitute
for professional care. It does not diagnose, treat, cure or prevent any medical
or psychological condition, and nothing it shows you is a clinical assessment.
The scores it records are your own self-reported numbers.</p>

<h2>3. Emergencies</h2>
<p>This service cannot help in an emergency. It is not monitored, there is no
one on the other end, and it does not detect distress. If you are in crisis or
at risk of harm, contact your local emergency number or a crisis line in your
country immediately.</p>

<h2>4. Do not delay care</h2>
<p>Do not use this app instead of seeking advice from a qualified professional,
and do not delay or stop treatment because of anything it suggests.</p>

<h2>5. Your responsibilities</h2>
<p>Use the practices sensibly. Do not use the session player while driving,
operating machinery, or anywhere that needs your attention. Stop any practice
that feels wrong for you. Mindful walking practices require somewhere safe to
walk; choosing that place is your responsibility.</p>

<h2>6. Acceptable use</h2>
<p>Do not attempt to disrupt the service, access other users' data, reverse the
pseudonymous identifiers, or use automated means to extract content at scale.</p>

<h2>7. Generated content</h2>
<p>The practice you are offered is selected by a deterministic rules engine, not
by a generative model. If AI-generated wording is introduced later, it will be
disclosed in the app, it will never change which practice or duration you are
given, and it may still produce wording that is unhelpful or wrong - your own
judgement remains the final check.</p>

<h2>8. Intellectual property</h2>
<p>The application, its practice content and its session protocols belong to the
operator. The contemplative methods they draw on are long-standing and are not
claimed as anyone's property. You may use the app for your own personal
practice.</p>

<h2>9. Availability</h2>
<p>This is a small service run by {operator.display_operator}. It may be
unavailable, interrupted or discontinued. No uptime is guaranteed, and you
should not depend on your history being retrievable at a particular moment.
Export it if it matters to you.</p>

<h2>10. Your data</h2>
<p>Handled as described in the privacy policy. You can export or delete
everything from inside the app at any time.</p>

<h2>11. Termination</h2>
<p>You can stop using the service at any time by deleting your data and removing
the app. The operator may suspend access that damages the service or other
users.</p>

<h2>12. No charge</h2>
<p>This version is provided at no cost and contains no subscription, no purchase
and no advertising. If paid features are introduced later, the terms that apply
to them will be presented before any charge.</p>

<h2>13. Disclaimers and liability</h2>
<p>The service is provided as is, without warranties of any kind. To the extent
permitted by applicable law, the operator is not liable for indirect or
consequential loss arising from your use of it. Nothing here limits liability
that cannot lawfully be limited, including for death or personal injury caused
by negligence.</p>

<h2>14. Governing law</h2>
<p>These terms are governed by the law of {operator.jurisdiction}. Any mandatory
consumer protections available to you where you live continue to apply.</p>

<h2>15. Changes</h2>
<p>Updated terms are published here with a new date at the top.</p>

<h2>16. Contact</h2>
<p>{operator.contact_email}</p>
"""


WELLNESS_DISCLAIMER_TITLE = "Before you start"

# Shown once, on one surface. Deliberately short: a warning repeated on every
# screen stops being read, which makes the product worse without making it safer.
WELLNESS_DISCLAIMER_BODY = (
    "This app supports mindfulness and general wellbeing. "
    "It is not a medical service and does not diagnose or treat any condition. "
    "It cannot help in an emergency - if you are in crisis, contact your local "
    "emergency number or a crisis line. "
    "Please do not delay professional care because of anything you see here."
)
