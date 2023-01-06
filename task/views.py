from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth import login, logout, authenticate
from django.db import IntegrityError
from .forms import TaskForm
from .models import Task
from django.utils import timezone
from django.contrib.auth.decorators import login_required

# Create your views here.


def home(request):
    return render(request, 'home.html', {
        'name' : home
    })


def signup(request):

    if request.method == 'GET':
        return render(request, 'signup.html', {
            'form': UserCreationForm
        })
    else:
        print(request.POST)
        if request.POST['password1'] == request.POST['password2']:
            try:
                # Register User
                user = User.objects.create_user(
                    username=request.POST['username'],email=request.POST['email'], password=request.POST['password1'])
                user.save()
                login(request, user)
                return redirect('tasks')
            except IntegrityError:
                return render(request, 'signup.html', {
                    'form': UserCreationForm,
                    'error': 'Username already exist'
                })
        return render(request, 'signup.html', {
            'form': UserCreationForm,
            'error': 'Password do not match',
            'mensajito' : 'Me cais bien, hazlo bien carita verga...'
        })

@login_required
def sigout(request):
    logout(request)
    return redirect('home')

def signin(request):
    if request.method == 'GET':
        return render(request, 'signin.html', {
            'form' : AuthenticationForm
        })
    elif request.method == 'POST':
        user = authenticate(request, username=request.POST['username'], password=request.POST['password'])
        if user is None:
            return render(request, 'signin.html', {
            'form' : AuthenticationForm,
            'error' : 'Username or password is incorrect. \n¿No te has registrado? ¡Ay ta!'
        })
        else:
            login(request, user)
            return redirect('tasks')

@login_required
def tasks(request):
    all_tasks = Task.objects.filter(user=request.user, datecompleted__isnull = True, important = False).order_by('-created')
    all_tasks |= Task.objects.filter(user=request.user, datecompleted__isnull = True, important = True).order_by('-created')
    all_tasks |= Task.objects.filter(user=request.user, datecompleted__isnull = False).order_by('-created')
    print(len(all_tasks))
    return render(request, 'task.html', {
        'tasks' : all_tasks,
        'title' : 'All Tasks',
        'user' : request.user,
        'cant' : len(all_tasks)
    })

@login_required
def tasks_completed(request):
    completed = Task.objects.filter(user=request.user, datecompleted__isnull = False).order_by('-created')
    print(request.user)
    return render(request, 'task.html', {
        'tasks' : completed,
        'title' : 'Tasks Completed',
        'user' : request.user
    })

@login_required
def tasks_pending(request):
    tasks = Task.objects.filter(user=request.user, datecompleted__isnull = True, important = False).order_by('-created')
    tasks |= Task.objects.filter(user=request.user, datecompleted__isnull = True, important = True).order_by('-created')
    print(request.user)
    return render(request, 'task.html', {
        'tasks' : tasks,
        'title' : 'Tasks Pending',
        'user' : request.user
    })
@login_required
def create_task(request):
    if request.method == 'GET':
        return render(request, 'create_task.html', {
            'form' : TaskForm
        })
    else:
        try:
            form = TaskForm(request.POST)
            new_task = form.save(commit = False)
            new_task.user = request.user
            new_task.save()
            return redirect('tasks')
        except ValueError:
            return render(request, 'create_task.html', {
            'form' : TaskForm,
            'error' : 'Please provide validate data'
        })

@login_required
def task_detail(request, task_id):
    if request.method == 'GET':
        task = get_object_or_404(Task, pk=task_id, user=request.user)        
        form = TaskForm(instance=task)
        return render(request, 'task_details.html', {
            'task' : task,
            'form' : form
        })
    else:
        try:
            task = get_object_or_404(Task, pk=task_id, user=request.user)
            form = TaskForm(request.POST, instance=task)
            form.save()
            return redirect('tasks')
        except ValueError:
            return render(request, 'task_details.html', {
            'task' : task,
            'form' : form,
            'error' : 'Error al actualizar la tarea, vuelva a intentarlo.'
            })

@login_required
def complete_task(request, task_id):
    task = get_object_or_404(Task, pk=task_id, user=request.user)
    print('Aquí estoy')
    if request.method == 'POST':
        task.datecompleted = timezone.now()
        task.save()
        return redirect('tasks')
    
@login_required
def delete_task(request, task_id):
    task = get_object_or_404(Task, pk=task_id, user = request.user)
    print('Delete acá')
    if request.method == 'POST':
        task.delete()
        return redirect('tasks')