<script lang="ts">
	import { Heart, Copy, Check, ExternalLink } from 'lucide-svelte';

	const PAYPAL_URL = 'https://www.paypal.com/donate/?hosted_button_id=G8WJPY25FRJHQ';
	const KOFI_URL = 'https://ko-fi.com/adamlprojects';
	const LIBERAPAY_URL = '';

	const cryptoAddresses = [
		{ name: 'DOGE', address: 'DQ4UQmEG848NAZYFowguuFZkFK26atd4y7' },
		{ name: 'BTC',  address: 'bc1qsl2msum3kkt4u5uhrnq3xf2zp29tpxhn8l3f2z' },
		{ name: 'LTC',  address: 'LbnGAHsx5YnwSZ7L6iW8hEG4BbiXqosghY' },
		{ name: 'ETH',  address: '0x572beD671646DcdB2D26003FC466F3d1EB608865' },
		{ name: 'USDT', address: '0x572beD671646DcdB2D26003FC466F3d1EB608865' },
		{ name: 'XRP',  address: 'ruFKp4cuutE374z7FeYSV2Hs8PXpCKeur' },
		{ name: 'BNB',  address: '0x572beD671646DcdB2D26003FC466F3d1EB608865' },
		{ name: 'USDC', address: '0x572beD671646DcdB2D26003FC466F3d1EB608865' },
		{ name: 'SOL',  address: 'Cis4vagxDZ6BTcE5aSnD4xfSP3211jZXwcZh9w4UVMsp' },
		{ name: 'TRX',  address: 'TUATjsR9PhUa2wYGWhCKCEVNzsXpQyQfVH' },
		{ name: 'ADA',  address: 'addr1q9acfxfmp48acx4vm9zafwdrna0g3vjrr8dt6jjeh3uw7smmsjvnkr20msd2ek296ju688673zeyxxw6h499n0rcaapsdlnnnr' },
		{ name: 'AVAX', address: '0x572beD671646DcdB2D26003FC466F3d1EB608865' },
	];

	let open = $state(false);
	let selectedIndex = $state(0);
	let copied = $state(false);

	const selected = $derived(cryptoAddresses[selectedIndex]);

	async function copyAddress() {
		await navigator.clipboard.writeText(selected.address);
		copied = true;
		setTimeout(() => (copied = false), 2000);
	}
</script>

<svelte:window onclick={() => open && (open = false)} />

<div
	class="fixed bottom-6 right-6 z-[1500] flex flex-col items-end gap-2"
	onclick={(e) => e.stopPropagation()}
	role="none"
>
	{#if open}
		<div class="w-72 bg-bg-secondary border border-border-color/60 rounded-2xl shadow-2xl overflow-hidden animate-in slide-in-from-bottom-2 fade-in duration-200">
			<div class="px-5 py-4 border-b border-border-color/40 bg-bg-tertiary/30">
				<p class="text-sm font-semibold text-text-primary">Support TapeHoard</p>
				<p class="text-xs text-text-secondary opacity-60 mt-0.5">Keep the project alive</p>
			</div>

			<div class="p-4 space-y-4">
				<!-- Crypto -->
				<div class="space-y-2">
					<p class="text-[10px] font-semibold uppercase tracking-wider text-text-secondary opacity-50">Cryptocurrency</p>
					<div class="flex gap-2">
						<div class="relative flex-1">
							<select
								bind:value={selectedIndex}
								class="w-full h-9 bg-bg-primary border border-border-color rounded-lg px-3 pr-8 text-xs text-text-primary outline-none appearance-none cursor-pointer focus:ring-2 focus:ring-blue-500/20"
							>
								{#each cryptoAddresses as addr, i}
									<option value={i}>{addr.name}</option>
								{/each}
							</select>
							<span class="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-text-secondary text-[10px]">▾</span>
						</div>
						<button
							onclick={copyAddress}
							class="h-9 w-9 shrink-0 flex items-center justify-center rounded-lg bg-bg-primary border border-border-color hover:border-blue-500/40 hover:bg-blue-500/5 transition-all text-text-secondary hover:text-text-primary"
							title="Copy address"
						>
							{#if copied}
								<Check size={14} class="text-green-500" />
							{:else}
								<Copy size={14} />
							{/if}
						</button>
					</div>
					<p class="text-[10px] font-mono text-text-secondary break-all bg-bg-primary/50 rounded-lg px-3 py-2 border border-border-color/40 select-all">
						{selected.address}
					</p>
				</div>

				<!-- Links -->
				{#if PAYPAL_URL || KOFI_URL || LIBERAPAY_URL}
					<div class="border-t border-border-color/40"></div>
					<div class="space-y-2">
						<p class="text-[10px] font-semibold uppercase tracking-wider text-text-secondary opacity-50">Other platforms</p>
						<div class="space-y-1.5">
							{#if PAYPAL_URL}
								<a
									href={PAYPAL_URL}
									target="_blank"
									rel="noopener noreferrer"
									class="flex items-center justify-between px-3 py-2 rounded-lg bg-bg-primary/40 border border-border-color/40 hover:border-blue-500/30 hover:bg-blue-500/5 transition-all group"
								>
									<span class="text-xs font-medium text-text-secondary group-hover:text-text-primary">PayPal</span>
									<ExternalLink size={12} class="text-text-secondary opacity-40 group-hover:opacity-100" />
								</a>
							{/if}
							{#if KOFI_URL}
								<a
									href={KOFI_URL}
									target="_blank"
									rel="noopener noreferrer"
									class="flex items-center justify-between px-3 py-2 rounded-lg bg-bg-primary/40 border border-border-color/40 hover:border-blue-500/30 hover:bg-blue-500/5 transition-all group"
								>
									<span class="text-xs font-medium text-text-secondary group-hover:text-text-primary">Ko-fi</span>
									<ExternalLink size={12} class="text-text-secondary opacity-40 group-hover:opacity-100" />
								</a>
							{/if}
							{#if LIBERAPAY_URL}
								<a
									href={LIBERAPAY_URL}
									target="_blank"
									rel="noopener noreferrer"
									class="flex items-center justify-between px-3 py-2 rounded-lg bg-bg-primary/40 border border-border-color/40 hover:border-blue-500/30 hover:bg-blue-500/5 transition-all group"
								>
									<span class="text-xs font-medium text-text-secondary group-hover:text-text-primary">Liberapay</span>
									<ExternalLink size={12} class="text-text-secondary opacity-40 group-hover:opacity-100" />
								</a>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		</div>
	{/if}

	<button
		onclick={(e) => { e.stopPropagation(); open = !open; }}
		class="flex items-center gap-1.5 h-8 px-3 rounded-full bg-bg-secondary/80 border border-border-color/50 text-text-secondary hover:text-text-primary hover:border-border-color hover:bg-bg-tertiary/80 transition-all shadow-lg backdrop-blur-sm text-xs font-medium"
		title="Support TapeHoard"
	>
		<Heart size={12} />
		<span>Support</span>
	</button>
</div>
