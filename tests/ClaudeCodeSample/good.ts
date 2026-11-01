import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

export async function getUserWithPosts(email: string) {
  return prisma.user.findUnique({
    where: { email },
    include: { posts: { where: { published: true }, orderBy: { id: "desc" } } },
  });
}

export async function createPost(authorId: number, title: string) {
  return prisma.post.create({
    data: { title, content: null, authorId },
    select: { id: true, title: true, author: { select: { name: true } } },
  });
}
