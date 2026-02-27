import { tool } from 'ai';
import { z } from 'zod';
import {
  generateCheckoutMandate,
  createIntentMandate,
  bindIntentMandate,
} from './ap2';

const CP_URL = process.env.CREDENTIAL_PROVIDER_URL || 'http://localhost:8002';
const BUSINESS_MCP_URL = process.env.BUSINESS_MCP_URL || 'http://localhost:8001/mcp/';

/**
 * The Credential Provider is a separate UCP participant (not part of the
 * merchant's MCP server), so this tool remains a direct REST call.
 */
export const getPaymentToken = tool({
  description: 'Get a payment token from the Credential Provider. Call this after the user confirms they want to pay, before completing checkout.',
  inputSchema: z.object({
    amount: z.number().describe('The total amount to charge'),
    currency: z.string().default('USD'),
    merchantName: z.string().default('Demo Electronics Store'),
  }),
  execute: async ({ amount, currency, merchantName }) => {
    const res = await fetch(`${CP_URL}/tokens`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: 'user_demo',
        amount,
        currency,
        merchant_name: merchantName,
      }),
    });
    return await res.json();
  },
});

/**
 * AP2 Cart Mandate — generates a checkout mandate (SD-JWT+kb) that
 * cryptographically binds the user's approval to a specific checkout session.
 */
export const generateCheckoutMandateTool = tool({
  description:
    'Generate an AP2 checkout mandate for a checkout session. Call this AFTER getting a payment token and BEFORE completing checkout. The mandate cryptographically proves the user approved this specific purchase.',
  inputSchema: z.object({
    sessionId: z.string().describe('The checkout session ID'),
  }),
  execute: async ({ sessionId }) => {
    const baseUrl = BUSINESS_MCP_URL.replace('/mcp/', '');
    const sessionRes = await fetch(`${baseUrl}/checkout-sessions/${sessionId}`);
    if (!sessionRes.ok) {
      return { error: `Failed to fetch session: ${sessionRes.status}` };
    }
    const session = await sessionRes.json();

    if (!session.ap2?.merchant_authorization) {
      return { error: 'Session missing merchant authorization' };
    }

    const mandate = await generateCheckoutMandate(session);
    return { checkout_mandate: mandate };
  },
});

/**
 * AP2 Intent Mandate — creates a pre-authorization for autonomous agent
 * purchases. The user specifies spending limits and scope; the agent can
 * then complete purchases without per-transaction user confirmation.
 *
 * This is a factory that captures the current conversation history.
 */
export function createIntentMandateToolWithMessages(
  messages: Array<{ role: string; content: string }>,
) {
  return tool({
    description:
      'Create an AP2 intent mandate for autonomous purchases. Use when the user wants to authorize future purchases without per-transaction approval. The mandate includes spending limits, merchant restrictions, and an expiration time.',
    inputSchema: z.object({
      maxAmountCents: z.number().describe('Maximum amount per transaction in cents (e.g. 5000 for $50)'),
      maxTotalCents: z.number().describe('Maximum total spend in cents across all uses'),
      currency: z.string().default('USD'),
      merchantIds: z.array(z.string()).describe('List of merchant/store IDs authorized'),
      maxUses: z.number().describe('Maximum number of transactions allowed'),
      expiresInHours: z.number().describe('Hours until mandate expires'),
      summary: z.string().describe('A concise human-readable summary of what is being authorized'),
    }),
    execute: async ({
      maxAmountCents,
      maxTotalCents,
      currency,
      merchantIds,
      maxUses,
      expiresInHours,
      summary,
    }) => {
      const turns = messages.map((m) => ({
        role: m.role,
        content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
      }));

      const result = await createIntentMandate({
        maxAmount: maxAmountCents,
        maxTotal: maxTotalCents,
        currency,
        merchantIds,
        maxUses,
        expiresInHours,
        conversation: {
          model: 'claude-sonnet-4-20250514',
          turns,
          turnCount: turns.length,
        },
        summary,
      });

      return result;
    },
  });
}

/**
 * Bind an intent mandate to a specific checkout session and complete it.
 * Used for autonomous agent purchases.
 */
export const bindAndCompleteWithIntentTool = tool({
  description:
    'Bind an intent mandate to a checkout session for autonomous completion. Use this instead of generateCheckoutMandate when completing a purchase under an existing intent mandate.',
  inputSchema: z.object({
    mandateId: z.string().describe('The intent mandate ID'),
    sessionId: z.string().describe('The checkout session ID'),
    amountCents: z.number().describe('Transaction amount in cents'),
  }),
  execute: async ({ mandateId, sessionId, amountCents }) => {
    const result = await bindIntentMandate(mandateId, sessionId, amountCents);
    if ('error' in result) {
      return { error: result.error };
    }
    return { intent_mandate: result.mandate };
  },
});
