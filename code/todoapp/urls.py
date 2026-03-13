from django.urls import path

from . import views

urlpatterns = [
    path("login", views.login_view, name="login"),
    path("logout", views.logout_view, name="logout"),
    path("createToDo", views.create_todo, name="create_todo"),
    path("done", views.mark_done, name="mark_done"),
    path("getToDos", views.get_todos, name="get_todos"),
    path("ai", views.ai_autocomplete, name="ai_autocomplete"),
    path("deleteAllToDos", views.delete_all_todos, name="delete_all_todos"),
]
