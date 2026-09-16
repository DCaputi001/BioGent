// HelpPage.tsx
// The "how to get an API key" walkthrough.
//
// ARCHITECTURE.md calls this the single biggest lever for the non-technical
// researcher goal, so it is written for someone who has never opened a
// developer console: every step names what to click, and the step people
// actually get stuck on (a key with no credit behind it) is called out
// rather than left to be discovered through a failed question.

const CONSOLE_URL = 'https://console.anthropic.com'
const BILLING_URL = 'https://console.anthropic.com/settings/billing'
const KEYS_URL = 'https://console.anthropic.com/settings/keys'

interface HelpPageProps {
  onBack: () => void
}

export function HelpPage({ onBack }: HelpPageProps) {
  return (
    <article className="help">
      <button type="button" className="link" onClick={onBack}>
        Back to questions
      </button>

      <h1>Getting an Anthropic API key</h1>

      <p className="lede">
        This app reads your documents, but the answers are written by Claude, an
        AI model made by Anthropic. You bring your own key to Claude, which
        means you pay Anthropic directly for the questions you ask. We never see
        your bill, and we never store your key.
      </p>

      <h2>What you will do</h2>
      <ol className="steps">
        <li>
          <strong>Create an Anthropic account.</strong> Go to{' '}
          <a href={CONSOLE_URL} target="_blank" rel="noreferrer noopener">
            console.anthropic.com
          </a>{' '}
          and sign up. This is separate from a Claude chat subscription, and
          from this app.
        </li>
        <li>
          <strong>Add credit.</strong> In the console, open{' '}
          <a href={BILLING_URL} target="_blank" rel="noreferrer noopener">
            Settings, then Billing
          </a>
          , and buy a small amount of credit to start.
        </li>
        <li>
          <strong>Create the key.</strong> Open{' '}
          <a href={KEYS_URL} target="_blank" rel="noreferrer noopener">
            Settings, then API keys
          </a>
          , choose <em>Create Key</em>, and give it a name you will recognize,
          such as "BioGent".
        </li>
        <li>
          <strong>Copy it immediately.</strong> The key is shown once, when you
          create it. If you navigate away without copying it, you cannot see it
          again; you simply create another one.
        </li>
        <li>
          <strong>Paste it into this app</strong> and start asking questions.
        </li>
      </ol>

      <h2 className="callout-heading">A key on its own is not enough</h2>
      <p className="callout">
        This is where most people get stuck. A brand-new key with no credit
        behind it will be rejected on your first question. If you see a message
        about credit, the key is fine and the account simply needs funds. Step 2
        above is the fix.
      </p>

      <h2>What a question costs</h2>
      <p>
        Each question sends the relevant passages from your documents to Claude
        along with your question, and you are billed by Anthropic for that
        usage. In practice a question costs a fraction of a cent to a few cents,
        depending on how much text is involved. You can see exact usage in the
        console, and you can set spending limits there.
      </p>

      <h2>What happens to your key here</h2>
      <ul>
        <li>It stays in this browser tab, and is sent with each question you ask.</li>
        <li>It is never saved on our servers, and never written to our database.</li>
        <li>Closing the tab clears it. You will paste it again next visit.</li>
        <li>
          You can delete a key at any time in{' '}
          <a href={KEYS_URL} target="_blank" rel="noreferrer noopener">
            the Anthropic console
          </a>
          . It stops working immediately, everywhere.
        </li>
      </ul>

      <button type="button" onClick={onBack}>
        Back to questions
      </button>
    </article>
  )
}
