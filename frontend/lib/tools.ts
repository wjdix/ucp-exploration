import { tool } from 'ai';
import { z } from 'zod';

const CP_URL = process.env.CREDENTIAL_PROVIDER_URL || 'http://localhost:8002';

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
