<script lang="ts">
	import type { HTMLInputAttributes } from "svelte/elements";
	import { cn } from "$lib/utils";

	let {
		class: className,
		value = $bindable(),
		...rest
	}: HTMLInputAttributes = $props();
</script>

<input
	class={cn(
		"flex h-10 w-full rounded-md border border-border-color bg-bg-primary px-3 py-2 text-sm text-text-primary ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-text-secondary/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-action-color disabled:cursor-not-allowed disabled:opacity-50 transition-all",
		className
	)}
	bind:value
	{...rest}
/>
