import { event } from 'jellycommands';
import { format } from 'date-fns';

export default event({
	name: 'messageCreate',
	async run(_, message) {
		if (message.author.bot) return;
		if (message.channelId != '1400529692225703966') return;

		const text = `${format(message.createdTimestamp, 'yyyy-MM-dd HH:mm:ss')}\n${message.author.displayName}:\n${message.content.slice(0, 100)}`;

		console.log(text);

		await fetch('http://127.0.0.1:5000/print/text', {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({
				font_size: 30,
				text,
			}),
		});
	},
});
