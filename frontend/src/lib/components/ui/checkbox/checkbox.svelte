<script lang="ts">
	import { Checkbox as CheckboxPrimitive } from "bits-ui";
	import { Check } from "lucide-svelte";
	import { cn } from "$lib/utils";

	let {
		class: className,
		checked = $bindable(false),
		...rest
	}: CheckboxPrimitive.Props = $props();
</script>

<CheckboxPrimitive.Root
	bind:checked
	class={cn(
		"peer h-4 w-4 shrink-0 rounded-sm border border-border-color bg-bg-primary ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action-color focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-action-color data-[state=checked]:border-action-color data-[state=checked]:text-white transition-all",
		className
	)}
	{...rest}
>
	{#if checked}
		<div class="flex items-center justify-center text-current h-full w-full">
			<Check class="h-3.5 w-3.5 stroke-[3]" />
		</div>
	{/if}
</CheckboxPrimitive.Root>
