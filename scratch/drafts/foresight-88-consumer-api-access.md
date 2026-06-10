# Draft board email — Consumer API access model for MCP

## Context
Related to foresight #88: https://github.com/freelawproject/foresight/discussions/88

## Draft email

Hi all,

I wanted to flag something for possible discussion at our meeting this weekend. I've been building a few small tools on top of our API that I'd love to share with lawyers/consumers, but right now, doing that means walking each person through API keys, worrying about whether they're storing the key somewhere insecure, and knowing they'll probably hit the rate limit before long. I think this is going to come to a head as the MCP design moves forward (foresight #88).

The basic issue: our API access model was built for developers, and MCP is going to bring in people who have no idea there's an API behind their tool. When they hit a rate limit, the current escalation path doesn't really make sense for an individual lawyer doing research.

I think we need three things:

1. A consumer access tier tied to membership. Someone using MCP for personal legal research might make a few thousand API calls a month. That's probably beyond what we'd want to give away for free, but it's not a partnership-level use case. Membership seems like a natural fit: include an API allowance and we turn MCP into a membership growth channel instead of creating 100s of new inbounds. For firms, the group membership tiers and Justice Partner Circle already give us a framework. This is a model I think I've heard discussed before, although I'm not sure how quickly it could be implemented.

2. OAuth instead of API keys. For consumer MCP to work, I think authorization would need to be more invisible than an API key can provide. The experience should be: install the CL MCP in Claude/Copilot/whatever, click "Connect with CourtListener," authorize in your browser, done.

3. Clear usage communication. The MCP should be able to tell a user "you've used 80% of your monthly allowance" or "upgrade your membership for more access" — not just fail silently. This is both good UX and good for conversion.

I'm raising this now because I'm worried that authorization and access patterns may be more difficult to change after the MCP launch, and changing them after launch may also cause us to miss the momentum and lose out on a chance to grow membership. It would be great to get a few minutes on this at our meeting this weekend.

Rebecca
