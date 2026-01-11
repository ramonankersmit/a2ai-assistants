60 seconden talk-track (voorlezen in demo)

“Wat je hier ziet is A2UI: agent-gedreven interfaces via berichten, niet via HTML.
De web-client is een vaste Overheid-achtige UI (Lit), maar de orchestrator stuurt het schermgedrag door A2UI-berichten over SSE.

Stap 1: ik kies een assistent. De orchestrator stuurt surface/open met het initiële dataModel.
Stap 2: als ik op ‘Check’ of ‘Analyseer’ druk, stuurt de UI een ClientEvent naar de orchestrator.
Stap 3: de orchestrator stuurt vervolgens progressive updates als losse dataModelUpdate patches: je ziet steeds A2UI: stappen, MCP: tool-calls met latency, en A2A: agent-calls met latency. Daardoor zie je continu voortgang én inhoud die groeit.

In deze MVP is de layout bewust vooraf ontworpen; de agent stuurt vooral state (status + results).
De deterministische onderdelen komen uit MCP-tools (regels/heuristiek). De meer ‘taal-achtige’ verrijking komt uit de A2A-agents, en bij Bezwaar kan Gemini een conceptbrief genereren (badge Gemini/Fallback).
Kort: A2UI is de ‘interface-laag’ die agent-output betrouwbaar, veilig en consistent renderbaar maakt.”