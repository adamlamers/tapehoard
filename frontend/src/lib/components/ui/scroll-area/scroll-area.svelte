<script lang="ts">
	import { cn } from "$lib/utils";
	import type { HTMLAttributes } from "svelte/elements";

	let { class: className, children, ...rest }: HTMLAttributes<HTMLDivElement> = $props();
</script>

<div
	class={cn("relative overflow-auto scrollbar-custom", className)}
	{...rest}
>
	{@render children?.()}
</div>

<style>
	:global(.scrollbar-custom::-webkit-scrollbar) {
		width: 8px;
		height: 8px;
	}

	:global(.scrollbar-custom::-webkit-scrollbar-track) {
		background: transparent;
	}

	:global(.scrollbar-custom::-webkit-scrollbar-thumb) {
		background: var(--color-border-color);
		border-radius: 10px;
		border: 2px solid var(--color-bg-secondary);
	}

	:global(.scrollbar-custom::-webkit-scrollbar-thumb:hover) {
		background: var(--color-text-secondary);
	}

	/* Firefox support */
	.scrollbar-custom {
		scrollbar-width: thin;
		scrollbar-color: var(--color-border-color) transparent;
	}
</style>
