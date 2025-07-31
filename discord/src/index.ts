import 'dotenv/config';
import { JellyCommands } from 'jellycommands';
import { IntentsBitField } from 'discord.js';

const client = new JellyCommands({
	// https://jellycommands.dev/components
	components: 'src/components',

	clientOptions: {
		intents: [
			IntentsBitField.Flags.Guilds,
			IntentsBitField.Flags.MessageContent,
			IntentsBitField.Flags.GuildMessages,
		],
	},

	dev: {
		// In testing we should enable this, it will make all our commands register in our testing guild
		// https://jellycommands.dev/components/commands/dev
		global: true,

		// Put your testing guild id here
		// https://jellycommands.dev/components/commands/dev
		guilds: ['663140687591768074'],
	},
});

// Automatically reads the DISCORD_TOKEN environment variable
client.login();
