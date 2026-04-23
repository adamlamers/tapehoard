<script lang="ts">
	import { Button as ButtonPrimitive } from "bits-ui";
	import { cn } from "$lib/utils";
	import { type Props, buttonVariants } from "./index.js";

	let {
		class: className,
		variant,
		size,
		children,
		builders,
		...rest
	}: Props = $props();
</script>

<ButtonPrimitive.Root
	class={cn(buttonVariants({ variant, size, className }))}
	{builders}
	{...rest}
>
	{@render children?.()}
</ButtonPrimitive.Root>
